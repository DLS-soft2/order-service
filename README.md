# Order Service

Saga state holder for the DLS-2 food delivery platform. Owns the order lifecycle and drives status transitions based on events from downstream services via Kafka.

## Setup

```bash
cp .env.example .env   # if exists, otherwise defaults work for local dev
poetry install
poetry run uvicorn app.main:app --port 8001 --reload
```

Requires PostgreSQL and Kafka — see `docker-compose.yaml` for local dev.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/orders/` | Create order (publishes `OrderCreated` to Kafka) |
| `GET` | `/api/v1/orders/{id}` | Get order by ID (excludes tombstoned) |
| `GET` | `/api/v1/orders/` | List orders with pagination (excludes tombstoned) |
| `DELETE` | `/api/v1/orders/{id}` | Tombstone an order (soft delete) |
| `GET` | `/api/v1/orders/{id}/snapshots` | Get full transition history |

## Kafka Topics

| Topic | Direction | Event Types |
|-------|-----------|-------------|
| `orders` | **Produces** | `OrderCreated` |
| `payments` | Consumes | `PaymentAuthorized`, `PaymentFailed` |
| `restaurants` | Consumes | `RestaurantAccepted` |
| `couriers` | Consumes | `CourierAssigned` |
| `deliveries` | Consumes | `DeliveryCompleted` |

## Order Status Flow

```
PENDING ──→ PAID ──→ PREPARING ──→ OUT_FOR_DELIVERY ──→ DELIVERED
   │          │          │                │
   └──────────┴──────────┴────────────────┘
                    CANCELLED
```

## Design Patterns

### Saga (Choreography)

The order-service is the saga state holder in a choreography-based saga — there is no central orchestrator. It publishes `OrderCreated` to the `orders` topic, then reacts to events from other services to advance the order through its lifecycle. Each service publishes events to its own topic, and the order-service consumes from all of them to track overall progress.

Status transitions are driven by incoming Kafka events:

| Event | Status Transition |
|-------|-------------------|
| `PaymentAuthorized` | PENDING → PAID |
| `PaymentFailed` | any → CANCELLED |
| `RestaurantAccepted` | PAID → PREPARING |
| `CourierAssigned` | PREPARING → OUT_FOR_DELIVERY |
| `DeliveryCompleted` | OUT_FOR_DELIVERY → DELIVERED |

### CQRS (Command Query Responsibility Segregation)

Write and read models are separated. The write model is the `Order` SQLAlchemy ORM class (`db/tables.py`), while the read model is the `OrderResponse` Pydantic schema (`models/orders.py`). The read model includes nested `OrderItemResponse` objects and excludes internal fields like `deleted_at`. This separation means the API response shape can evolve independently of the database schema.

### Tombstone Pattern

Orders are never physically deleted. Instead, a `DELETE` request inserts an immutable row into the `order_tombstones` table — a separate table that records the deletion timestamp. The original order row is never modified or removed. All read queries use a `LEFT JOIN` against the tombstones table and filter out tombstoned orders. This preserves the full audit trail while respecting deletion requests.

### Snapshot Pattern

An `OrderSnapshot` is created at every status transition and at initial order creation. Each snapshot captures the order's full state (status, amount, delivery address) as a JSON blob in the `order_snapshots` table. The `GET /api/v1/orders/{id}/snapshots` endpoint exposes the complete transition history. This allows reconstructing the order's state at any point in time without replaying events.

### Idempotent Consumers

Every Kafka event carries an `event_id` (UUID). Before processing, the consumer checks the `processed_events` table — if the `event_id` already exists, the event is skipped. After successful processing, the event ID is recorded. This prevents duplicate side effects when Kafka redelivers messages (e.g. after a consumer restart or rebalance).

### Commutative Message Handlers

Kafka does not guarantee cross-topic ordering. If `RestaurantAccepted` arrives before `PaymentAuthorized`, the system must still converge to the correct state. This is achieved through a numeric ranking system:

```python
STATUS_ORDER = {
    "PENDING": 0, "PAID": 1, "PREPARING": 2,
    "OUT_FOR_DELIVERY": 3, "DELIVERED": 4, "CANCELLED": 99
}
```

The `can_transition` guard only allows forward movement — a transition is accepted only if the target rank is strictly greater than the current rank. This means:
- Out-of-order events that would advance the status are accepted (e.g. skipping from PENDING to PREPARING)
- Events that would regress the status are silently rejected (e.g. PAID → PENDING)
- Terminal states (DELIVERED, CANCELLED) reject all further transitions

The result is eventual consistency regardless of message arrival order.

## Database

PostgreSQL with 5 tables:

| Table | Purpose |
|-------|---------|
| `orders` | Core order data and current status |
| `order_items` | Line items within an order |
| `order_snapshots` | Immutable state capture at each transition |
| `order_tombstones` | Immutable deletion markers |
| `processed_events` | Kafka event deduplication |

Migrations managed by **Alembic** (`alembic/versions/`).

## Tests

```bash
poetry run pytest -v              # 55 tests
poetry run pylint app/            # >= 9.0/10
```
