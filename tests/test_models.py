import uuid
from app.models import Order, OrderItem, OrderSnapshot, ProcessedEvent


def test_create_order(db):
    """An order can be inserted and queried."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=49.99,
        delivery_address="123 Main St",
    )
    db.add(order)
    db.commit()

    result = db.query(Order).first()
    assert result is not None
    assert result.status == "PENDING"
    assert result.total_amount == 49.99


def test_order_deleted_at_defaults_to_none(db):
    """Order.deleted_at defaults to None (Tombstone pattern foundation)."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=10.0,
        delivery_address="456 Elm St",
    )
    db.add(order)
    db.commit()

    result = db.query(Order).first()
    assert result.deleted_at is None


def test_create_order_item_linked_to_order(db):
    """An OrderItem can be created with a foreign key to an Order."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=25.00,
        delivery_address="789 Oak Ave",
    )
    db.add(order)
    db.commit()

    item = OrderItem(
        order_id=order.id,
        menu_item_id=uuid.uuid4(),
        name="Margherita Pizza",
        quantity=2,
        unit_price=12.50,
    )
    db.add(item)
    db.commit()

    result = db.query(OrderItem).first()
    assert result.order_id == order.id
    assert result.name == "Margherita Pizza"
    assert result.quantity == 2

    # Verify relationship
    db.refresh(order)
    assert len(order.items) == 1
    assert order.items[0].id == item.id


def test_create_order_snapshot_linked_to_order(db):
    """An OrderSnapshot captures order state at a point in time."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=30.00,
        delivery_address="321 Pine Rd",
    )
    db.add(order)
    db.commit()

    snapshot = OrderSnapshot(
        order_id=order.id,
        status="PENDING",
        snapshot_data={"total_amount": 30.00, "items": []},
    )
    db.add(snapshot)
    db.commit()

    result = db.query(OrderSnapshot).first()
    assert result.order_id == order.id
    assert result.status == "PENDING"
    assert result.snapshot_data["total_amount"] == 30.00

    # Verify relationship
    db.refresh(order)
    assert len(order.snapshots) == 1


def test_create_processed_event(db):
    """A ProcessedEvent records a consumed Kafka event for idempotency."""
    event = ProcessedEvent(
        event_id="evt-abc-123",
        topic="payments",
    )
    db.add(event)
    db.commit()

    result = db.query(ProcessedEvent).filter_by(event_id="evt-abc-123").first()
    assert result is not None
    assert result.topic == "payments"
    assert result.processed_at is not None


def test_order_items_cascade_with_order(db):
    """Deleting an order cascades to its items."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=50.00,
        delivery_address="555 Birch Ln",
    )
    db.add(order)
    db.commit()

    item = OrderItem(
        order_id=order.id,
        menu_item_id=uuid.uuid4(),
        name="Caesar Salad",
        quantity=1,
        unit_price=50.00,
    )
    db.add(item)
    db.commit()

    db.delete(order)
    db.commit()

    assert db.query(OrderItem).count() == 0


def test_root_endpoint(client):
    """Service info endpoint returns name and version."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "order-service"


def test_health_endpoint(client):
    """Health check returns healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
