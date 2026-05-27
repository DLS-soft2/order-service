from uuid import UUID
from sqlalchemy.orm import Session, joinedload
from app.db.tables import Order, OrderItem, OrderSnapshot, OrderTombstone
from app.models.orders import OrderCreate


def create_order(data: OrderCreate, db: Session) -> Order:
    """Create a new order with items.

    Computes total_amount from items, persists Order + OrderItems,
    creates an initial OrderSnapshot capturing the PENDING state.
    """
    total_amount = sum(item.quantity * item.unit_price for item in data.items)

    order = Order(
        customer_id=data.customer_id,
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
    db.commit()
    db.refresh(order)

    return order


def get_order(order_id: UUID, db: Session) -> Order | None:
    """Fetch an order by ID, excluding tombstoned orders.

    Uses LEFT JOIN against order_tombstones to implement the tombstone pattern.
    Returns None if the order does not exist or has been tombstoned.
    """
    return (
        db.query(Order)
        .outerjoin(OrderTombstone, Order.id == OrderTombstone.order_id)
        .filter(Order.id == order_id, OrderTombstone.order_id.is_(None))
        .options(joinedload(Order.items))
        .first()
    )


def list_orders(skip: int, limit: int, db: Session) -> list[Order]:
    """List orders with pagination, excluding tombstoned orders.

    Uses LEFT JOIN against order_tombstones to filter out
    logically deleted orders (tombstone pattern).
    """
    return (
        db.query(Order)
        .outerjoin(OrderTombstone, Order.id == OrderTombstone.order_id)
        .filter(OrderTombstone.order_id.is_(None))
        .options(joinedload(Order.items))
        .offset(skip)
        .limit(limit)
        .all()
    )
