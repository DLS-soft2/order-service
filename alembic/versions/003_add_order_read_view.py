from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create and backfill the order read projection."""
    op.create_table(
        "order_read_view",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("customer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_amount", sa.Numeric(), nullable=False),
        sa.Column("delivery_address", sa.String(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_order_read_view_customer_id", "order_read_view", ["customer_id"])
    op.create_index("ix_order_read_view_status", "order_read_view", ["status"])
    op.create_index(
        "ix_order_read_view_customer_status",
        "order_read_view",
        ["customer_id", "status"],
    )
    op.execute(
        """
        INSERT INTO order_read_view (
            id,
            customer_id,
            restaurant_id,
            status,
            total_amount,
            delivery_address,
            items,
            created_at,
            updated_at,
            tombstoned_at
        )
        SELECT
            orders.id,
            orders.customer_id,
            orders.restaurant_id,
            orders.status,
            orders.total_amount,
            orders.delivery_address,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', order_items.id,
                        'menu_item_id', order_items.menu_item_id,
                        'name', order_items.name,
                        'quantity', order_items.quantity,
                        'unit_price', order_items.unit_price
                    )
                    ORDER BY order_items.id
                ) FILTER (WHERE order_items.id IS NOT NULL),
                '[]'::json
            ),
            orders.created_at,
            orders.updated_at,
            order_tombstones.tombstoned_at
        FROM orders
        LEFT JOIN order_items ON order_items.order_id = orders.id
        LEFT JOIN order_tombstones ON order_tombstones.order_id = orders.id
        GROUP BY orders.id, order_tombstones.tombstoned_at
        """
    )


def downgrade() -> None:
    """Drop the order read projection."""
    op.drop_table("order_read_view")
