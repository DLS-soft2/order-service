from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session
from app.config import settings
from app.db.tables import Order, OrderItem, OrderReadView, OrderSnapshot, OrderTombstone
from app.kafka.producer import publish_event
from app.models.events import OrderCreated
from app.models.orders import OrderCreate


async def create_order(data: OrderCreate, customer_id: UUID, db: Session) -> Order:
    """Create a new order with items and publish an OrderCreated event.

    Computes total_amount from items, persists Order + OrderItems,
    creates an initial OrderSnapshot capturing the PENDING state,
    then publishes an OrderCreated event to Kafka.
    """
    total_amount = sum(item.quantity * item.unit_price for item in data.items)

    order = Order(
        customer_id=customer_id,
        restaurant_id=data.restaurant_id,
        delivery_address=data.delivery_address,
        total_amount=total_amount,
    )
    db.add(order)
    db.flush()

    order_items = [
        OrderItem(
            order_id=order.id,
            menu_item_id=item.menu_item_id,
            name=item.name,
            quantity=item.quantity,
            unit_price=item.unit_price,
        )
        for item in data.items
    ]
    db.add_all(order_items)
    db.flush()

    snapshot = OrderSnapshot(
        order_id=order.id,
        status="PENDING",
        snapshot_data={
            "total_amount": total_amount,
            "delivery_address": data.delivery_address,
            "items": [item.model_dump(mode="json") for item in data.items],
        },
    )
    db.add(snapshot)
    upsert_order_read_view(order, order_items, db)
    db.commit()
    db.refresh(order)

    event = OrderCreated(
        order_id=order.id,
        customer_id=order.customer_id,
        restaurant_id=order.restaurant_id,
        amount=order.total_amount,
        delivery_address=order.delivery_address,
        timestamp=datetime.now(timezone.utc),
    )
    await publish_event(
        topic=settings.kafka_topic_orders,
        event_data=event.model_dump(mode="json"),
        key=str(order.id),
    )

    return order


def upsert_order_read_view(order: Order, items: list[OrderItem], db: Session) -> OrderReadView:
    """Create or update the order read projection from the write model."""
    item_data = [
        {
            "id": str(item.id),
            "menu_item_id": str(item.menu_item_id),
            "name": item.name,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
        }
        for item in items
    ]
    read_view = db.query(OrderReadView).filter(OrderReadView.id == order.id).first()
    if read_view is None:
        read_view = OrderReadView(id=order.id)
        db.add(read_view)

    read_view.customer_id = order.customer_id
    read_view.restaurant_id = order.restaurant_id
    read_view.status = order.status
    read_view.total_amount = order.total_amount
    read_view.delivery_address = order.delivery_address
    read_view.items = item_data
    read_view.created_at = order.created_at
    read_view.updated_at = order.updated_at
    return read_view


def mark_order_read_view_tombstoned(order_id: UUID, db: Session) -> None:
    """Set tombstoned_at on the order read projection."""
    read_view = db.query(OrderReadView).filter(OrderReadView.id == order_id).first()
    if read_view is None:
        raise ValueError("Order read view not found")

    read_view.tombstoned_at = datetime.now(timezone.utc)


def get_order(order_id: UUID, db: Session) -> OrderReadView | None:
    """Fetch an order read projection by ID, excluding tombstoned orders."""
    return (
        db.query(OrderReadView)
        .filter(OrderReadView.id == order_id, OrderReadView.tombstoned_at.is_(None))
        .first()
    )


def list_orders(skip: int, limit: int, db: Session) -> list[OrderReadView]:
    """List order read projections with pagination, excluding tombstoned orders."""
    return (
        db.query(OrderReadView)
        .filter(OrderReadView.tombstoned_at.is_(None))
        .offset(skip)
        .limit(limit)
        .all()
    )


def tombstone_order(order_id: UUID, db: Session) -> bool:
    """Mark an order as deleted by inserting into order_tombstones (tombstone pattern).

    The original order row is never modified or removed.
    Returns True on success. Raises ValueError if the order does not
    exist or is already tombstoned.
    """
    order = (
        db.query(Order)
        .outerjoin(OrderTombstone, Order.id == OrderTombstone.order_id)
        .filter(Order.id == order_id, OrderTombstone.order_id.is_(None))
        .first()
    )
    if not order:
        raise ValueError("Order not found or already tombstoned")

    tombstone = OrderTombstone(order_id=order_id)
    db.add(tombstone)
    mark_order_read_view_tombstoned(order_id, db)
    db.commit()
    return True


def list_orders_by_customer(
    customer_id: UUID, skip: int, limit: int, db: Session,
) -> list[OrderReadView]:
    """List order read projections for a customer, excluding tombstoned orders."""
    return (
        db.query(OrderReadView)
        .filter(
            OrderReadView.customer_id == customer_id,
            OrderReadView.tombstoned_at.is_(None),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_order_snapshots(order_id: UUID, db: Session) -> list[OrderSnapshot]:
    """Return all snapshots for an order, ordered by created_at ascending.

    Raises ValueError if the order does not exist.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Order not found")

    return (
        db.query(OrderSnapshot)
        .filter(OrderSnapshot.order_id == order_id)
        .order_by(OrderSnapshot.created_at.asc())
        .all()
    )
