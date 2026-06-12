import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.db.tables import Order, OrderReadView, OrderSnapshot, OrderTombstone

AUTH_HEADERS = {"x-user-id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11", "x-user-roles": "customer"}


def _order_payload(**overrides) -> dict:
    """Build a valid OrderCreate request body with optional overrides."""
    defaults = {
        "restaurant_id": str(uuid.uuid4()),
        "delivery_address": "123 Test St",
        "items": [
            {
                "menu_item_id": str(uuid.uuid4()),
                "name": "Margherita Pizza",
                "quantity": 2,
                "unit_price": 12.50,
            },
        ],
    }
    defaults.update(overrides)
    return defaults


def _tombstone_read_view(order_id: uuid.UUID, db) -> None:
    read_view = db.query(OrderReadView).filter_by(id=order_id).one()
    read_view.tombstoned_at = datetime.now(timezone.utc)


def test_create_order(client):
    """POST /api/v1/orders/ creates an order and returns 201."""
    payload = _order_payload()
    response = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "PENDING"
    assert data["total_amount"] == 25.0  # 2 * 12.50
    assert data["delivery_address"] == "123 Test St"
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Margherita Pizza"
    assert data["customer_id"] == AUTH_HEADERS["x-user-id"]
    assert data["restaurant_id"] == payload["restaurant_id"]


def test_create_order_computes_total_from_multiple_items(client):
    """POST computes total_amount as sum of (quantity * unit_price) across items."""
    payload = _order_payload(items=[
        {"menu_item_id": str(uuid.uuid4()), "name": "Pizza", "quantity": 2, "unit_price": 10.0},
        {"menu_item_id": str(uuid.uuid4()), "name": "Soda", "quantity": 3, "unit_price": 3.0},
    ])
    response = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json()["total_amount"] == 29.0  # (2*10) + (3*3)


def test_create_order_validates_items_not_empty(client):
    """POST rejects an order with an empty items list."""
    payload = _order_payload(items=[])
    response = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_create_order_missing_user_header(client):
    """POST returns 401 when x-user-id header is absent."""
    response = client.post("/api/v1/orders/", json=_order_payload(), headers={"x-user-roles": "customer"})
    assert response.status_code == 401


def test_create_order_invalid_user_header(client):
    """POST returns 400 when x-user-id header is not a valid UUID."""
    headers = {"x-user-id": "not-a-uuid", "x-user-roles": "customer"}
    response = client.post("/api/v1/orders/", json=_order_payload(), headers=headers)
    assert response.status_code == 400


def test_create_order_creates_initial_snapshot(client, db):
    """POST creates an OrderSnapshot with status PENDING."""
    payload = _order_payload()
    response = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)
    order_id = uuid.UUID(response.json()["id"])

    snapshot = db.query(OrderSnapshot).filter_by(order_id=order_id).first()
    assert snapshot is not None
    assert snapshot.status == "PENDING"
    assert snapshot.snapshot_data["total_amount"] == response.json()["total_amount"]


def test_create_order_creates_read_projection(client, db):
    """POST creates an OrderReadView row with serialized item data."""
    payload = _order_payload()
    response = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)
    order_id = uuid.UUID(response.json()["id"])

    read_views = db.query(OrderReadView).all()
    assert len(read_views) == 1
    read_view = read_views[0]
    assert read_view.id == order_id
    assert str(read_view.customer_id) == AUTH_HEADERS["x-user-id"]
    assert str(read_view.restaurant_id) == payload["restaurant_id"]
    assert read_view.status == "PENDING"
    assert float(read_view.total_amount) == response.json()["total_amount"]
    assert read_view.delivery_address == payload["delivery_address"]
    assert read_view.tombstoned_at is None
    assert read_view.items == [
        {
            "id": response.json()["items"][0]["id"],
            "menu_item_id": payload["items"][0]["menu_item_id"],
            "name": payload["items"][0]["name"],
            "quantity": payload["items"][0]["quantity"],
            "unit_price": payload["items"][0]["unit_price"],
        }
    ]


def test_get_order_by_id(client):
    """GET /api/v1/orders/{id} returns the order with nested items."""
    payload = _order_payload()
    create_resp = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)
    order_id = create_resp.json()["id"]

    response = client.get(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == order_id
    assert len(data["items"]) == 1
    assert data["items"][0]["menu_item_id"] == payload["items"][0]["menu_item_id"]
    assert data["items"][0]["name"] == payload["items"][0]["name"]
    assert data["items"][0]["quantity"] == payload["items"][0]["quantity"]
    assert data["items"][0]["unit_price"] == payload["items"][0]["unit_price"]


def test_get_order_ignores_write_table_without_read_projection(client, db):
    """GET and list endpoints ignore orders absent from the read projection."""
    order = Order(
        customer_id=uuid.UUID(AUTH_HEADERS["x-user-id"]),
        restaurant_id=uuid.uuid4(),
        delivery_address="123 Write Table St",
        total_amount=10.0,
    )
    db.add(order)
    db.commit()

    get_response = client.get(f"/api/v1/orders/{order.id}", headers=AUTH_HEADERS)
    list_response = client.get("/api/v1/orders/", headers=AUTH_HEADERS)
    customer_response = client.get(
        f"/api/v1/orders/customer/{order.customer_id}", headers=AUTH_HEADERS,
    )

    assert get_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json() == []
    assert customer_response.status_code == 200
    assert customer_response.json() == []


def test_get_order_not_found(client):
    """GET /api/v1/orders/{id} returns 404 for a non-existent order."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/v1/orders/{fake_id}", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_list_orders_empty(client):
    """GET /api/v1/orders/ returns an empty list on a fresh database."""
    response = client.get("/api/v1/orders/", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_list_orders_with_data(client):
    """GET /api/v1/orders/ returns created orders."""
    client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)

    response = client.get("/api/v1/orders/", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_orders_pagination(client):
    """GET /api/v1/orders/ respects skip and limit parameters."""
    for _ in range(3):
        client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)

    response = client.get("/api/v1/orders/?skip=0&limit=2", headers=AUTH_HEADERS)
    assert len(response.json()) == 2

    response = client.get("/api/v1/orders/?skip=2&limit=2", headers=AUTH_HEADERS)
    assert len(response.json()) == 1


def test_list_orders_by_customer_filters_correctly(client):
    """GET /api/v1/orders/customer/{id} returns only that customer's orders."""
    customer_a = str(uuid.uuid4())
    customer_b = str(uuid.uuid4())
    headers_a = {"x-user-id": customer_a, "x-user-roles": "customer"}
    headers_b = {"x-user-id": customer_b, "x-user-roles": "customer"}

    client.post("/api/v1/orders/", json=_order_payload(), headers=headers_a)
    client.post("/api/v1/orders/", json=_order_payload(), headers=headers_a)
    client.post("/api/v1/orders/", json=_order_payload(), headers=headers_b)

    response = client.get(f"/api/v1/orders/customer/{customer_a}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(o["customer_id"] == customer_a for o in data)

    response = client.get(f"/api/v1/orders/customer/{customer_b}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["customer_id"] == customer_b


def test_list_orders_by_customer_excludes_tombstoned(client, db):
    """GET /api/v1/orders/customer/{id} excludes tombstoned orders."""
    customer_id = str(uuid.uuid4())
    headers = {"x-user-id": customer_id, "x-user-roles": "customer"}
    resp1 = client.post("/api/v1/orders/", json=_order_payload(), headers=headers)
    client.post("/api/v1/orders/", json=_order_payload(), headers=headers)

    order_to_tombstone = resp1.json()["id"]
    tombstone = OrderTombstone(order_id=uuid.UUID(order_to_tombstone))
    db.add(tombstone)
    _tombstone_read_view(uuid.UUID(order_to_tombstone), db)
    db.commit()

    response = client.get(f"/api/v1/orders/customer/{customer_id}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] != order_to_tombstone


def test_list_orders_by_customer_empty(client):
    """GET /api/v1/orders/customer/{id} returns empty list for unknown customer."""
    unknown = uuid.uuid4()
    response = client.get(f"/api/v1/orders/customer/{unknown}", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_tombstoned_order_excluded_from_get_by_id(client, db):
    """GET /api/v1/orders/{id} returns 404 for a tombstoned order."""
    create_resp = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id = create_resp.json()["id"]

    # Verify order is accessible before tombstoning
    assert client.get(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS).status_code == 200

    # Insert tombstone
    tombstone = OrderTombstone(order_id=uuid.UUID(order_id))
    db.add(tombstone)
    _tombstone_read_view(uuid.UUID(order_id), db)
    db.commit()

    # Order should now be 404
    response = client.get(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_tombstoned_order_excluded_from_list(client, db):
    """GET /api/v1/orders/ excludes tombstoned orders from the list."""
    resp1 = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    resp2 = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id_to_tombstone = resp1.json()["id"]
    surviving_order_id = resp2.json()["id"]

    # Verify both are listed
    assert len(client.get("/api/v1/orders/", headers=AUTH_HEADERS).json()) == 2

    # Tombstone the first order
    tombstone = OrderTombstone(order_id=uuid.UUID(order_id_to_tombstone))
    db.add(tombstone)
    _tombstone_read_view(uuid.UUID(order_id_to_tombstone), db)
    db.commit()

    # Only the non-tombstoned order should remain
    response = client.get("/api/v1/orders/", headers=AUTH_HEADERS)
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == surviving_order_id


@patch("app.service.order_service.publish_event", new_callable=AsyncMock)
def test_create_order_publishes_event(mock_publish, client):
    """POST /api/v1/orders/ publishes an OrderCreated event via Kafka."""
    payload = _order_payload()
    response = client.post("/api/v1/orders/", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 201
    mock_publish.assert_called_once()
    call_kwargs = mock_publish.call_args.kwargs
    assert call_kwargs["topic"] == "orders"
    assert call_kwargs["key"] == response.json()["id"]
    event_data = call_kwargs["event_data"]
    assert event_data["event_type"] == "OrderCreated"
    assert event_data["order_id"] == response.json()["id"]


# --- Tombstone endpoint tests ---


def test_tombstone_order_returns_204(client):
    """DELETE /api/v1/orders/{id} tombstones the order and returns 204."""
    create_resp = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id = create_resp.json()["id"]

    response = client.delete(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS)
    assert response.status_code == 204


def test_tombstone_order_updates_read_projection(client, db):
    """DELETE sets tombstoned_at on the OrderReadView row."""
    create_resp = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id = uuid.UUID(create_resp.json()["id"])

    response = client.delete(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS)

    read_view = db.query(OrderReadView).filter_by(id=order_id).one()
    tombstones = db.query(OrderTombstone).filter_by(order_id=order_id).all()
    assert response.status_code == 204
    assert len(tombstones) == 1
    assert read_view.tombstoned_at is not None


def test_tombstoned_order_returns_404_on_get(client):
    """GET /api/v1/orders/{id} returns 404 after tombstoning via DELETE."""
    create_resp = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id = create_resp.json()["id"]

    client.delete(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS)
    response = client.get(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_tombstoned_order_excluded_from_list_via_endpoint(client):
    """GET /api/v1/orders/ excludes orders tombstoned via DELETE endpoint."""
    resp1 = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    resp2 = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    tombstoned_id = resp1.json()["id"]
    surviving_id = resp2.json()["id"]

    client.delete(f"/api/v1/orders/{tombstoned_id}", headers=AUTH_HEADERS)

    response = client.get("/api/v1/orders/", headers=AUTH_HEADERS)
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == surviving_id


def test_tombstone_already_tombstoned_returns_404(client):
    """DELETE on an already-tombstoned order returns 404."""
    create_resp = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id = create_resp.json()["id"]

    assert client.delete(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS).status_code == 204
    assert client.delete(f"/api/v1/orders/{order_id}", headers=AUTH_HEADERS).status_code == 404


def test_tombstone_nonexistent_order_returns_404(client):
    """DELETE on a non-existent order returns 404."""
    fake_id = uuid.uuid4()
    response = client.delete(f"/api/v1/orders/{fake_id}", headers=AUTH_HEADERS)
    assert response.status_code == 404


# --- Snapshot endpoint tests ---


def test_snapshot_endpoint_returns_initial_snapshot(client):
    """GET /api/v1/orders/{id}/snapshots returns the PENDING snapshot after creation."""
    create_resp = client.post("/api/v1/orders/", json=_order_payload(), headers=AUTH_HEADERS)
    order_id = create_resp.json()["id"]

    response = client.get(f"/api/v1/orders/{order_id}/snapshots", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["order_id"] == order_id
    assert data[0]["status"] == "PENDING"
    assert "total_amount" in data[0]["snapshot_data"]


def test_snapshot_endpoint_nonexistent_order_returns_404(client):
    """GET /api/v1/orders/{id}/snapshots returns 404 for a non-existent order."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/v1/orders/{fake_id}/snapshots", headers=AUTH_HEADERS)
    assert response.status_code == 404
