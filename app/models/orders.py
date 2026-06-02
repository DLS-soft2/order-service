from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator


class OrderItemCreate(BaseModel):
    """Input schema for a single line item when creating an order."""

    menu_item_id: UUID
    name: str
    quantity: int
    unit_price: float

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, value: int) -> int:
        """Quantity must be at least 1."""
        if value < 1:
            raise ValueError("quantity must be at least 1")
        return value


class OrderCreate(BaseModel):
    """Input schema for creating an order (write model)."""

    customer_id: UUID
    restaurant_id: UUID
    delivery_address: str
    items: list[OrderItemCreate]

    @field_validator("items")
    @classmethod
    def items_must_not_be_empty(cls, value: list[OrderItemCreate]) -> list[OrderItemCreate]:
        """An order must have at least one item."""
        if not value:
            raise ValueError("items must not be empty")
        return value


class OrderItemResponse(BaseModel):
    """Read model for a single line item in an order response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    menu_item_id: UUID
    name: str
    quantity: int
    unit_price: float


class OrderResponse(BaseModel):
    """CQRS read model — flattened order representation for API consumers.

    Structurally different from the Order ORM model:
    - Excludes DB-internal fields (order_id FKs on items, relationship objects)
    - Includes nested OrderItemResponse list (transformed from ORM relationship)
    - Uses ConfigDict(from_attributes=True) for automatic ORM-to-schema conversion
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    restaurant_id: UUID
    status: str
    total_amount: float
    delivery_address: str
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime


class OrderSnapshotResponse(BaseModel):
    """Read model for an immutable order snapshot (Snapshot pattern)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    status: str
    snapshot_data: dict
    created_at: datetime
