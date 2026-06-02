from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.db.tables import Order, OrderSnapshot
from app.models.orders import OrderCreate, OrderResponse, OrderSnapshotResponse
from app.service import order_service

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.post("/", response_model=OrderResponse, status_code=201)
async def create_order(body: OrderCreate, db: Session = Depends(get_db)) -> Order:
    """Create a new order with items."""
    return await order_service.create_order(body, db)


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


@router.delete("/{order_id}", status_code=204, response_class=Response)
def delete_order(order_id: UUID, db: Session = Depends(get_db)) -> None:
    """Tombstone an order (immutable deletion marker). Original row is not modified."""
    try:
        order_service.tombstone_order(order_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{order_id}/snapshots", response_model=list[OrderSnapshotResponse],
)
def get_order_snapshots(
    order_id: UUID, db: Session = Depends(get_db),
) -> list[OrderSnapshot]:
    """Return the full snapshot history for an order (Snapshot pattern)."""
    try:
        return order_service.get_order_snapshots(order_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
