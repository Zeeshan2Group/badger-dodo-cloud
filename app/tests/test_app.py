import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import create_app, next_roast_day  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.setenv("ENABLE_STRESS", "true")
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}")
    app.config["TESTING"] = True
    return app.test_client()


def test_health_reports_database(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["database"] is True


def test_products_are_seeded(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"House Espresso Blend" in res.data


def test_order_is_saved_and_appears_in_plan(client):
    res = client.post("/orders", data={"partner": "Harbour Café", "county": "Cork",
                                       "product_id": "2", "kg": "12.5"})
    assert res.status_code == 302
    orders = client.get("/api/orders").get_json()
    assert orders[0]["partner"] == "Harbour Café"
    assert orders[0]["county"] == "Cork"
    assert orders[0]["kg"] == 12.5
    assert orders[0]["standing"] is False
    assert b"12.50" in client.get("/").data


def test_standing_orders_add_to_next_roast(client):
    client.post("/orders", data={"partner": "A", "county": "Kerry", "product_id": "1",
                                 "kg": "4", "standing": "on"})
    client.post("/orders", data={"partner": "B", "county": "Cork", "product_id": "1",
                                 "kg": "6"})
    orders = client.get("/api/orders").get_json()
    assert [o["standing"] for o in orders] == [False, True]
    page = client.get("/").data
    assert b"10.00" in page          # 4 kg standing + 6 kg one-off, same coffee and day
    assert b"weekly" in page


def test_invalid_order_is_rejected(client):
    client.post("/orders", data={"partner": "", "county": "Cork", "product_id": "1", "kg": "5"})
    client.post("/orders", data={"partner": "X", "county": "Cork", "product_id": "1", "kg": "-1"})
    client.post("/orders", data={"partner": "X", "county": "Cork", "product_id": "99", "kg": "5"})
    client.post("/orders", data={"partner": "X", "county": "Atlantis", "product_id": "1", "kg": "5"})
    assert client.get("/api/orders").get_json() == []


def test_export_requires_bucket(client, monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    res = client.post("/roast-plan/export")
    assert "S3_BUCKET" in res.headers["Location"].replace("%20", " ")


def test_stress_is_capped(client):
    res = client.get("/stress?seconds=1")
    assert res.get_json()["burned_seconds"] == 1


def test_next_roast_day_is_tuesday_or_friday():
    for d in range(1, 15):
        assert next_roast_day(date(2026, 11, d)).weekday() in (1, 4)
