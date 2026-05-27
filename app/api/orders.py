from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.db.tables import Order
from app.models.orders import OrderCreate, OrderResponse
from app.service import order_service

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.post("/", response_model=OrderResponse, status_code=201)
def create_order(body: OrderCreate, db: Session = Depends(get_db)) -> Order:
    """Create a new order with items."""
    return order_service.create_order(body, db)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: UUID, db: Session = Depends(get_db)) -> Order:
    """Get a single order by ID. Returns 404 if not found or tombstoned."""
    order = order_service.get_order(order_id, db)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/", response_model=list[OrderResponse])
def list_orders(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[Order]:
    """List orders with pagination, excluding tombstoned orders."""
    return order_service.list_orders(skip, limit, db)
