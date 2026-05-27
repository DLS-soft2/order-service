from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


# Kafka event schemas for the Order Service.

# Events OUT (produced to "orders" topic):
#   - OrderCreated: a new order has been placed, downstream services react

# Events IN (consumed from payments/restaurants/couriers/deliveries):
#   - PaymentAuthorized, PaymentFailed, RestaurantAccepted,
#     CourierAssigned, DeliveryCompleted



class OrderCreated(BaseModel):
    """Event published to the 'orders' topic when a new order is created."""

    event_type: str = "OrderCreated"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    customer_id: UUID
    restaurant_id: UUID
    amount: float
    delivery_address: str
    timestamp: datetime


# --- Consumed events ---


class PaymentAuthorized(BaseModel):
    """Payment was successfully authorized for an order."""

    event_type: str = "PaymentAuthorized"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    payment_id: UUID
    amount: float
    timestamp: datetime


class PaymentFailed(BaseModel):
    """Payment failed — order should be cancelled."""

    event_type: str = "PaymentFailed"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    reason: str
    timestamp: datetime


class RestaurantAccepted(BaseModel):
    """Restaurant accepted the order and started preparing."""

    event_type: str = "RestaurantAccepted"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    estimated_prep_time: int
    timestamp: datetime


class CourierAssigned(BaseModel):
    """A courier has been assigned to pick up and deliver the order."""

    event_type: str = "CourierAssigned"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    courier_id: UUID
    timestamp: datetime


class DeliveryCompleted(BaseModel):
    """The order has been delivered to the customer."""

    event_type: str = "DeliveryCompleted"
    event_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    timestamp: datetime
