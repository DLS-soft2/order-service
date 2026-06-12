"""Tests for saga transition logic.

Covers all transition scenarios including forward progression,
cancellation, terminal state rejection, regression rejection,
and commutative (skip-ahead) transitions.
"""

from datetime import datetime, timezone
import uuid

from app.db.tables import Order, OrderReadView, OrderSnapshot
from app.service.saga import can_transition, apply_transition


# --- can_transition tests ---


def test_pending_to_paid_allowed():
    """PENDING -> PAID is a valid forward transition."""
    assert can_transition("PENDING", "PAID") is True


def test_pending_to_cancelled_allowed():
    """PENDING -> CANCELLED is always allowed from non-terminal."""
    assert can_transition("PENDING", "CANCELLED") is True


def test_paid_to_preparing_allowed():
    """PAID -> PREPARING is a valid forward transition."""
    assert can_transition("PAID", "PREPARING") is True


def test_preparing_to_out_for_delivery_allowed():
    """PREPARING -> OUT_FOR_DELIVERY is a valid forward transition."""
    assert can_transition("PREPARING", "OUT_FOR_DELIVERY") is True


def test_out_for_delivery_to_delivered_allowed():
    """OUT_FOR_DELIVERY -> DELIVERED is a valid forward transition."""
    assert can_transition("OUT_FOR_DELIVERY", "DELIVERED") is True


def test_delivered_to_any_rejected():
    """DELIVERED is terminal — no further transitions allowed."""
    assert can_transition("DELIVERED", "PENDING") is False
    assert can_transition("DELIVERED", "PAID") is False
    assert can_transition("DELIVERED", "CANCELLED") is False


def test_cancelled_to_any_rejected():
    """CANCELLED is terminal — no further transitions allowed."""
    assert can_transition("CANCELLED", "PENDING") is False
    assert can_transition("CANCELLED", "PAID") is False


def test_paid_to_pending_rejected():
    """PAID -> PENDING is a regression — rejected by commutative guard."""
    assert can_transition("PAID", "PENDING") is False


def test_pending_to_delivered_allowed_commutative():
    """PENDING -> DELIVERED is allowed by commutative guard (skip-ahead)."""
    assert can_transition("PENDING", "DELIVERED") is True


# --- apply_transition tests ---


def _make_order(db, status: str = "PENDING") -> Order:
    """Create a persisted order and matching read projection."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=25.0,
        delivery_address="42 Test Lane",
        status=status,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderReadView(
            id=order.id,
            customer_id=order.customer_id,
            restaurant_id=order.restaurant_id,
            status=order.status,
            total_amount=order.total_amount,
            delivery_address=order.delivery_address,
            items=[],
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
    )
    db.commit()
    return order


def test_apply_transition_updates_status(db):
    """apply_transition updates order and projection status."""
    order = _make_order(db, "PENDING")
    result = apply_transition(order, "PAID", db)

    read_view = db.query(OrderReadView).filter_by(id=order.id).one()
    assert result is True
    assert order.status == "PAID"
    assert read_view.status == "PAID"


def test_apply_transition_creates_snapshot(db):
    """apply_transition creates an OrderSnapshot with the new status."""
    order = _make_order(db, "PENDING")
    apply_transition(order, "PAID", db)

    snapshots = db.query(OrderSnapshot).filter_by(order_id=order.id).all()
    assert len(snapshots) == 1
    assert snapshots[0].status == "PAID"
    assert snapshots[0].snapshot_data["order_id"] == str(order.id)


def test_apply_transition_rejected_returns_false(db):
    """apply_transition returns False and makes no changes when rejected."""
    order = _make_order(db, "DELIVERED")
    original_updated_at = order.updated_at
    read_view = db.query(OrderReadView).filter_by(id=order.id).one()
    read_view.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()
    original_read_view_updated_at = read_view.updated_at

    result = apply_transition(order, "PAID", db)

    db.refresh(read_view)
    assert result is False
    assert order.status == "DELIVERED"
    assert order.updated_at == original_updated_at
    assert read_view.status == "DELIVERED"
    assert read_view.updated_at == original_read_view_updated_at
    assert db.query(OrderSnapshot).filter_by(order_id=order.id).count() == 0


def test_apply_transition_updates_updated_at(db):
    """apply_transition sets order.updated_at to a new timestamp."""
    order = _make_order(db, "PENDING")
    original_updated_at = order.updated_at

    apply_transition(order, "PAID", db)

    assert order.updated_at >= original_updated_at


# --- Saga failure transition tests ---


def test_restaurant_rejected_cancels_paid_order(db):
    """A PAID order transitions to CANCELLED via RestaurantRejected."""
    order = _make_order(db, "PAID")
    result = apply_transition(order, "CANCELLED", db)

    assert result is True
    assert order.status == "CANCELLED"


def test_courier_assignment_failed_cancels_preparing_order(db):
    """A PREPARING order transitions to CANCELLED via CourierAssignmentFailed."""
    order = _make_order(db, "PREPARING")
    result = apply_transition(order, "CANCELLED", db)

    assert result is True
    assert order.status == "CANCELLED"


def test_payment_refunded_cancels_any_non_terminal_order(db):
    """PaymentRefunded can cancel an order from any non-terminal status."""
    for status in ("PENDING", "PAID", "PREPARING", "OUT_FOR_DELIVERY"):
        order = _make_order(db, status)
        result = apply_transition(order, "CANCELLED", db)

        assert result is True
        assert order.status == "CANCELLED"


def test_valid_transitions_contains_failure_events():
    """VALID_TRANSITIONS maps all three failure events to CANCELLED."""
    from app.service.saga import VALID_TRANSITIONS

    assert VALID_TRANSITIONS["RestaurantRejected"] == "CANCELLED"
    assert VALID_TRANSITIONS["CourierAssignmentFailed"] == "CANCELLED"
    assert VALID_TRANSITIONS["PaymentRefunded"] == "CANCELLED"


def test_valid_transitions_has_eight_entries():
    """VALID_TRANSITIONS has exactly 8 entries (5 original + 3 failure)."""
    from app.service.saga import VALID_TRANSITIONS

    assert len(VALID_TRANSITIONS) == 8
