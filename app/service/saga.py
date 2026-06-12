from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.db.tables import Order, OrderSnapshot


# Saga transition logic for order status management.

# Implements commutative guards: status can only advance forward
# (higher rank), never regress. CANCELLED is allowed from any
# non-terminal state. DELIVERED and CANCELLED are terminal.

# Each transition creates an immutable OrderSnapshot.



STATUS_ORDER: dict[str, int] = {
    "PENDING": 0,
    "PAID": 1,
    "PREPARING": 2,
    "OUT_FOR_DELIVERY": 3,
    "DELIVERED": 4,
    "CANCELLED": 99,
}

VALID_TRANSITIONS: dict[str, str] = {
    "PaymentAuthorized": "PAID",
    "PaymentFailed": "CANCELLED",
    "RestaurantAccepted": "PREPARING",
    "RestaurantRejected": "CANCELLED",
    "CourierAssigned": "OUT_FOR_DELIVERY",
    "CourierAssignmentFailed": "CANCELLED",
    "DeliveryCompleted": "DELIVERED",
    "PaymentRefunded": "CANCELLED",
}

TERMINAL_STATUSES = {"DELIVERED", "CANCELLED"}


def can_transition(current_status: str, target_status: str) -> bool:
    """Check whether a status transition is allowed.

    Rules:
      - No transitions from terminal states (DELIVERED, CANCELLED).
      - CANCELLED is allowed from any non-terminal state.
      - Otherwise, target rank must be strictly greater than current rank.
    """
    if current_status in TERMINAL_STATUSES:
        return False

    if target_status == "CANCELLED":
        return True

    current_rank = STATUS_ORDER.get(current_status, -1)
    target_rank = STATUS_ORDER.get(target_status, -1)
    return target_rank > current_rank


def apply_transition(order: Order, target_status: str, db: Session) -> bool:
    """Apply a status transition to an order if allowed.

    Updates order.status and order.updated_at, creates an OrderSnapshot
    capturing the new state. Returns True if the transition was applied,
    False if it was rejected by can_transition.
    """
    if not can_transition(order.status, target_status):
        return False

    order.status = target_status
    order.updated_at = datetime.now(timezone.utc)

    snapshot = OrderSnapshot(
        order_id=order.id,
        status=target_status,
        snapshot_data={
            "order_id": str(order.id),
            "status": target_status,
            "total_amount": order.total_amount,
            "delivery_address": order.delivery_address,
        },
    )
    db.add(snapshot)
    db.commit()

    return True
