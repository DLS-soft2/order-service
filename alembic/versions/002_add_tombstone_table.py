"""Add order_tombstones table.

Revision ID: 002
Revises: 001
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create order_tombstones table for the tombstone pattern."""
    op.create_table(
        "order_tombstones",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", name="uq_order_tombstones_order_id"),
    )


def downgrade() -> None:
    """Drop order_tombstones table."""
    op.drop_table("order_tombstones")
