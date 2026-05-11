# tests/unit/test_orders.py
"""Tests for routers/orders.py — the RBAC matrix per endpoint."""


# ---------- POST /orders/ (anyone authenticated) ----------

class TestCreateOrder:

    def test_admin_can_place_order(self, admin_client):
        r = admin_client.post("/orders/", json={"item_name": "Espresso", "quantity": 1})
        assert r.status_code == 201
        assert r.json()["item_name"] == "Espresso"
        assert r.json()["is_completed"] is False

    def test_barista_can_place_order(self, barista_client):
        r = barista_client.post("/orders/", json={"item_name": "Espresso", "quantity": 1})
        assert r.status_code == 201

    def test_regular_user_can_place_order(self, regular_client):
        r = regular_client.post("/orders/", json={"item_name": "Espresso", "quantity": 1})
        assert r.status_code == 201

    def test_viewer_can_place_order_via_api(self, viewer_client):
        # Viewer's UI hides the button, but the API still accepts the call
        # (server-side enforcement of "no orders" for viewers would actually
        # be inconsistent — viewers can place orders, they just can't see
        # the queue afterwards).
        r = viewer_client.post("/orders/", json={"item_name": "Espresso", "quantity": 1})
        assert r.status_code == 201

    def test_unauthenticated_returns_401(self, client):
        r = client.post("/orders/", json={"item_name": "Espresso", "quantity": 1})
        assert r.status_code == 401

    def test_quantity_must_be_positive(self, regular_client):
        r = regular_client.post("/orders/", json={"item_name": "Espresso", "quantity": 0})
        assert r.status_code == 422

    def test_negative_quantity_rejected(self, regular_client):
        r = regular_client.post("/orders/", json={"item_name": "Espresso", "quantity": -5})
        assert r.status_code == 422

    def test_order_tracks_placer(self, regular_client, regular_user):
        r = regular_client.post("/orders/", json={"item_name": "Latte", "quantity": 2})
        assert r.status_code == 201
        body = r.json()
        assert body["placed_by_username"] == regular_user.username


# ---------- GET /orders/ (admin, barista, viewer) ----------

class TestListOrders:

    def test_admin_can_list(self, admin_client):
        r = admin_client.get("/orders/")
        assert r.status_code == 200

    def test_barista_can_list(self, barista_client):
        r = barista_client.get("/orders/")
        assert r.status_code == 200

    def test_viewer_can_list(self, viewer_client):
        r = viewer_client.get("/orders/")
        assert r.status_code == 200

    def test_user_cannot_list(self, regular_client):
        """Users place orders but don't see the queue."""
        r = regular_client.get("/orders/")
        assert r.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/orders/")
        assert r.status_code == 401

    def test_orders_returned_newest_first(self, admin_client):
        for item in ["A", "B", "C"]:
            admin_client.post("/orders/", json={"item_name": item, "quantity": 1})
        r = admin_client.get("/orders/")
        items = [o["item_name"] for o in r.json()]
        assert items[:3] == ["C", "B", "A"]

    def test_pagination_skip_and_limit(self, admin_client):
        for i in range(5):
            admin_client.post("/orders/", json={"item_name": f"item_{i}", "quantity": 1})
        r = admin_client.get("/orders/?skip=2&limit=2")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_includes_placed_by_username(self, admin_client, regular_client, regular_user):
        regular_client.post("/orders/", json={"item_name": "TrackedItem", "quantity": 1})
        r = admin_client.get("/orders/")
        order = next(o for o in r.json() if o["item_name"] == "TrackedItem")
        assert order["placed_by_username"] == regular_user.username


# ---------- PUT /orders/{id}/complete (admin, barista) ----------

class TestCompleteOrder:

    def _place_order(self, c, item="Espresso"):
        r = c.post("/orders/", json={"item_name": item, "quantity": 1})
        return r.json()["id"]

    def test_admin_can_complete(self, admin_client):
        order_id = self._place_order(admin_client)
        r = admin_client.put(f"/orders/{order_id}/complete")
        assert r.status_code == 200
        assert r.json()["is_completed"] is True

    def test_barista_can_complete(self, barista_client, admin_client):
        order_id = self._place_order(admin_client)
        r = barista_client.put(f"/orders/{order_id}/complete")
        assert r.status_code == 200

    def test_user_cannot_complete(self, regular_client, admin_client):
        order_id = self._place_order(admin_client)
        r = regular_client.put(f"/orders/{order_id}/complete")
        assert r.status_code == 403

    def test_viewer_cannot_complete(self, viewer_client, admin_client):
        order_id = self._place_order(admin_client)
        r = viewer_client.put(f"/orders/{order_id}/complete")
        assert r.status_code == 403

    def test_unauthenticated_returns_401(self, client):
        r = client.put("/orders/1/complete")
        assert r.status_code == 401

    def test_complete_nonexistent_returns_404(self, admin_client):
        r = admin_client.put("/orders/99999/complete")
        assert r.status_code == 404
