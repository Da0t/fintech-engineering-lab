import pytest
from fastapi.testclient import TestClient
import clearledger.api as ledger_api
import marketlab.api as market_api
from clearledger.ledger import Ledger
from marketlab.bridge import Market
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path / "api.sqlite")
    ledger.seed()
    monkeypatch.setattr(ledger_api, "_ledger", ledger)
    market = Market()
    monkeypatch.setattr(market_api, "market", market)
    with TestClient(app) as client:
        yield client
    market.close()


def test_pages_and_health(client):
    for path in ["/", "/clearledger", "/marketlab", "/health", "/docs", "/static/app.js"]:
        assert client.get(path).status_code == 200


def test_api_recovery_workflow(client):
    incident = client.post("/api/ledger/incident").json()
    result = client.post(f"/api/ledger/events/{incident['event_id']}/retry")
    assert result.status_code == 200
    state = client.get("/api/ledger/state").json()
    assert all(state["checks"].values())
    assert all(r["status"] == "matched" for r in state["reconciliation"])


@pytest.mark.parametrize("amount", [1.5,True,"100",-1])
def test_api_rejects_noninteger_or_negative_money(client, amount):
    assert client.post("/api/ledger/events", json={"event_id":"e", "payment_id":"p", "amount":amount}).status_code == 422


def test_market_api_validation_and_replay(client):
    assert client.post("/api/market/orders", json={"id":"x\nRESET", "side":"buy", "type":"market", "quantity":1}).status_code == 422
    response = client.post("/api/market/orders", json={"id":"x", "side":"buy", "type":"market", "quantity":50})
    assert response.status_code == 200
    assert response.json()["result"]["filled"] == 50
    assert client.post("/api/market/replay").json()["result"]["identical"]
