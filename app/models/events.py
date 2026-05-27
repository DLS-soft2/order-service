"""Kafka event schemas for the Order Service.

Events OUT (produced to "orders" topic):
  - OrderCreated: a new order has been placed, downstream services react
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class OrderCreated(BaseModel):
    """Event published to the 'orders' topic when a new order is created.

    Consumed by Payment Service, Restaurant Service, and others.
    Contains everything downstream services need to begin processing.
    """

    event_type: str = "OrderCreated"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    customer_id: UUID
    restaurant_id: UUID
    amount: float
    delivery_address: str
    timestamp: datetime
