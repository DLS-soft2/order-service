import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Integer, DateTime, ForeignKey, JSON, Uuid, Index, UniqueConstraint,
    Numeric,
)
from sqlalchemy.orm import relationship
from app.database import Base


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


class Order(Base):
    """Represents a customer order — the saga state holder."""

    __tablename__ = "orders"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    restaurant_id = Column(Uuid(as_uuid=True), nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    total_amount = Column(Float, nullable=False)
    delivery_address = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False,
    )

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    snapshots = relationship("OrderSnapshot", back_populates="order", cascade="all, delete-orphan")
    tombstone = relationship("OrderTombstone", uselist=False, back_populates="order")

    __table_args__ = (
        Index("ix_orders_status", "status"),
    )


class OrderItem(Base):
    """A single line item within an order."""

    __tablename__ = "order_items"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(Uuid(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Uuid(as_uuid=True), nullable=False)
    name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")


class OrderSnapshot(Base):
    """Immutable snapshot of order state captured at each status transition."""

    __tablename__ = "order_snapshots"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(Uuid(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    status = Column(String, nullable=False)
    snapshot_data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    order = relationship("Order", back_populates="snapshots")


class OrderTombstone(Base):
    """Immutable deletion marker for an order (tombstone pattern).

    Records that an order has been logically deleted without modifying or
    removing the original order row.  Reads LEFT JOIN against this table
    to filter out tombstoned orders.
    """

    __tablename__ = "order_tombstones"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(
        Uuid(as_uuid=True), ForeignKey("orders.id"), nullable=False,
    )
    tombstoned_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)

    order = relationship("Order", back_populates="tombstone")

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_order_tombstones_order_id"),
    )


class OrderReadView(Base):
    """Read projection for order query paths."""

    __tablename__ = "order_read_view"

    id = Column(Uuid(as_uuid=True), primary_key=True)
    customer_id = Column(Uuid(as_uuid=True), nullable=False, index=True)
    restaurant_id = Column(Uuid(as_uuid=True), nullable=False)
    status = Column(String, nullable=False, index=True)
    total_amount = Column(Numeric, nullable=False)
    delivery_address = Column(String, nullable=False)
    items = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False,
    )
    tombstoned_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_order_read_view_customer_status", "customer_id", "status"),
    )


class ProcessedEvent(Base):
    """Tracks consumed Kafka event IDs for idempotency."""

    __tablename__ = "processed_events"

    event_id = Column(String, primary_key=True)
    topic = Column(String, nullable=False)
    processed_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
