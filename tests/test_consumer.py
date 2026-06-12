"""Tests for the Kafka consumer event handling.

Covers idempotency, order lookup, saga transition triggering,
and snapshot creation on each consumed event.
"""

import uuid

from app.db.tables import Order, OrderSnapshot, ProcessedEvent
from app.kafka.consumer import handle_event, is_event_processed, mark_event_processed


def _make_order(db, status: str = "PENDING") -> Order:
    """Create a persisted order with the given status."""
    order = Order(
        customer_id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        total_amount=30.0,
        delivery_address="99 Consumer St",
        status=status,
    )
    db.add(order)
    db.commit()
    return order


def test_payment_authorized_transitions_to_paid(db):
    """A PaymentAuthorized event transitions a PENDING order to PAID."""
    order = _make_order(db, "PENDING")
    event = {
        "event_type": "PaymentAuthorized",
        "event_id": str(uuid.uuid4()),
        "order_id": str(order.id),
        "payment_id": str(uuid.uuid4()),
        "amount": 30.0,
        "timestamp": "2026-05-28T12:00:00Z",
    }

    handle_event(event, "payments", db)

    db.refresh(order)
    assert order.status == "PAID"


def test_duplicate_event_skipped(db):
    """Processing the same event_id twice does not create a second transition."""
    order = _make_order(db, "PENDING")
    event_id = str(uuid.uuid4())
    event = {
        "event_type": "PaymentAuthorized",
        "event_id": event_id,
        "order_id": str(order.id),
        "payment_id": str(uuid.uuid4()),
        "amount": 30.0,
        "timestamp": "2026-05-28T12:00:00Z",
    }

    handle_event(event, "payments", db)
    handle_event(event, "payments", db)

    db.refresh(order)
    assert order.status == "PAID"
    snapshots = db.query(OrderSnapshot).filter_by(order_id=order.id).all()
    assert len(snapshots) == 1


def test_event_for_nonexistent_order_skipped(db):
    """An event referencing a non-existent order is skipped without error."""
    event = {
        "event_type": "PaymentAuthorized",
        "event_id": str(uuid.uuid4()),
        "order_id": str(uuid.uuid4()),
        "payment_id": str(uuid.uuid4()),
        "amount": 30.0,
        "timestamp": "2026-05-28T12:00:00Z",
    }

    handle_event(event, "payments", db)

    assert db.query(Order).count() == 0


def test_payment_failed_transitions_to_cancelled(db):
    """A PaymentFailed event transitions a PENDING order to CANCELLED."""
    order = _make_order(db, "PENDING")
    event = {
        "event_type": "PaymentFailed",
        "event_id": str(uuid.uuid4()),
        "order_id": str(order.id),
        "reason": "Insufficient funds",
        "timestamp": "2026-05-28T12:00:00Z",
    }

    handle_event(event, "payments", db)

    db.refresh(order)
    assert order.status == "CANCELLED"


def test_snapshot_created_on_transition(db):
    """Each successful transition creates an OrderSnapshot."""
    order = _make_order(db, "PAID")
    event = {
        "event_type": "RestaurantAccepted",
        "event_id": str(uuid.uuid4()),
        "order_id": str(order.id),
        "estimated_prep_time": 15,
        "timestamp": "2026-05-28T12:00:00Z",
    }

    handle_event(event, "restaurants", db)

    db.refresh(order)
    assert order.status == "PREPARING"
    snapshot = db.query(OrderSnapshot).filter_by(order_id=order.id, status="PREPARING").first()
    assert snapshot is not None
    assert snapshot.snapshot_data["status"] == "PREPARING"


def test_missing_event_id_skipped(db):
    """An event without event_id is skipped and nothing is recorded."""
    order = _make_order(db, "PENDING")
    event = {
        "event_type": "PaymentAuthorized",
        "order_id": str(order.id),
        "amount": 30.0,
    }

    handle_event(event, "payments", db)

    db.refresh(order)
    assert order.status == "PENDING"
    assert db.query(ProcessedEvent).count() == 0


def test_missing_order_id_skipped(db):
    """An event without order_id is skipped and nothing is recorded."""
    event = {
        "event_type": "PaymentAuthorized",
        "event_id": str(uuid.uuid4()),
        "amount": 30.0,
    }

    handle_event(event, "payments", db)

    assert db.query(ProcessedEvent).count() == 0


def test_restaurant_rejected_transitions_to_cancelled(db):
    """A RestaurantRejected event transitions a PAID order to CANCELLED."""
    order = _make_order(db, "PAID")
    event = {
        "event_type": "RestaurantRejected",
        "event_id": str(uuid.uuid4()),
        "order_id": str(order.id),
        "restaurant_id": str(uuid.uuid4()),
        "reason": "Kitchen closed",
        "timestamp": "2026-06-11T12:00:00Z",
    }

    handle_event(event, "restaurants", db)

    db.refresh(order)
    assert order.status == "CANCELLED"


def test_is_event_processed_returns_false_for_new(db):
    """is_event_processed returns False for an unseen event_id."""
    assert is_event_processed("never-seen-id", db) is False


def test_mark_and_check_event_processed(db):
    """mark_event_processed + is_event_processed roundtrip."""
    event_id = str(uuid.uuid4())
    mark_event_processed(event_id, "payments", db)
    assert is_event_processed(event_id, db) is True
    assert db.query(ProcessedEvent).filter_by(event_id=event_id).first().topic == "payments"
