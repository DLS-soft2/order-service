"""Initial schema — orders, order_items, order_snapshots, processed_events.

Revision ID: 001
Revises: None
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all four tables."""
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("customer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("delivery_address", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("order_id", sa.Uuid(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
    )

    op.create_table(
        "order_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("order_id", sa.Uuid(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("snapshot_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop all four tables in reverse dependency order."""
    op.drop_table("processed_events")
    op.drop_table("order_snapshots")
    op.drop_table("order_items")
    op.drop_table("orders")
