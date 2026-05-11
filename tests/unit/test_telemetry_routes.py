# tests/unit/test_telemetry_routes.py
"""Tests for routers/telemetry.py — metrics math and access control."""


class TestTelemetryAccess:

    def test_admin_can_get_metrics(self, admin_client):
        r = admin_client.get("/telemetry/metrics")
        assert r.status_code == 200

    def test_admin_can_get_logs(self, admin_client):
        r = admin_client.get("/telemetry/logs")
        assert r.status_code == 200

    def test_barista_cannot_get_metrics(self, barista_client):
        r = barista_client.get("/telemetry/metrics")
        assert r.status_code == 403

    def test_viewer_cannot_get_metrics(self, viewer_client):
        r = viewer_client.get("/telemetry/metrics")
        assert r.status_code == 403

    def test_user_cannot_get_metrics(self, regular_client):
        r = regular_client.get("/telemetry/metrics")
        assert r.status_code == 403

    def test_unauthenticated_cannot_get_metrics(self, client):
        r = client.get("/telemetry/metrics")
        assert r.status_code == 401


class TestMetricsMath:

    def test_metrics_empty_when_no_logs(self, admin_client, app_module, db):
        """Fresh DB — no logs yet (well, the login itself creates one, but
        let's see what the structure looks like)."""
        r = admin_client.get("/telemetry/metrics")
        data = r.json()
        # Structure check
        assert "total_requests" in data
        assert "average_latency_ms" in data
        assert "p95_latency_ms" in data
        assert "error_count" in data
        assert "system_health" in data

    def test_metrics_with_logs(self, admin_client, db):
        """Generate some logs by making a few requests, then check metrics."""
        import models
        # Add some manual log rows
        for ms in [10.0, 20.0, 30.0, 40.0, 50.0, 100.0, 200.0]:
            db.add(models.SystemLog(
                endpoint="/test",
                method="GET",
                status_code=200,
                response_time_ms=ms,
            ))
        db.commit()
        r = admin_client.get("/telemetry/metrics")
        data = r.json()
        assert data["total_requests"] >= 7
        assert data["p95_latency_ms"] > 0

    def test_metrics_error_count_with_500s(self, admin_client, db):
        import models
        for status in [200, 200, 500, 500, 503]:
            db.add(models.SystemLog(
                endpoint="/test",
                method="GET",
                status_code=status,
                response_time_ms=10.0,
            ))
        db.commit()
        r = admin_client.get("/telemetry/metrics")
        data = r.json()
        assert data["error_count"] >= 3
        assert data["system_health"] == "Degraded"

    def test_logs_limit_param(self, admin_client, db):
        import models
        for i in range(30):
            db.add(models.SystemLog(
                endpoint=f"/test/{i}",
                method="GET",
                status_code=200,
                response_time_ms=10.0,
            ))
        db.commit()
        r = admin_client.get("/telemetry/logs?limit=5")
        assert r.status_code == 200
        assert len(r.json()) == 5
