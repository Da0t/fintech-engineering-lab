from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from app import create_app


@pytest.fixture
def client():
    with TestClient(create_app(public=True)) as client:
        yield client


def fresh():
    return {"version":1,"started_at":datetime.now(timezone.utc).isoformat(),"history":[]}


def call(client, session, path, body=None):
    response=client.post("/api/demo",json={"path":path,"body":body,"session":session})
    assert response.status_code==200, response.text
    result=response.json()
    session.update(result["session"])
    return result["value"]


def test_public_mode_hides_shared_local_apis(client):
    assert client.get("/api/config").json()["public_demo"]
    assert client.get("/api/ledger/state").status_code==404
    assert client.get("/api/market/state").status_code==404
    assert client.post("/api/ledger/incident").status_code==404


def test_ledger_visitors_are_isolated_and_refresh_is_identical(client):
    a,b=fresh(),fresh()
    initial=call(client,b,"/api/ledger/state")
    call(client,a,"/api/ledger/holds",{"hold_id":"new_hold","amount":5000})
    state=call(client,a,"/api/ledger/state")
    assert state["balances"]["wallet"]==285000
    assert state==call(client,a,"/api/ledger/state")
    assert call(client,b,"/api/ledger/state")==initial


def test_public_incident_recovery_and_refund(client):
    session=fresh()
    incident=call(client,session,"/api/ledger/incident",{})
    state=call(client,session,"/api/ledger/state")
    assert state["balances"]["wallet"]==290000
    assert state["inbox"][0]["id"]==incident["event_id"]
    call(client,session,f"/api/ledger/events/{incident['event_id']}/retry",{})
    call(client,session,"/api/ledger/refunds",{"payment_id":incident["payment_id"],"amount":2500,"key":"r1"})
    call(client,session,"/api/ledger/provider-records",{"record_id":"ref1","payment_id":incident["payment_id"],"kind":"refund","amount":2500})
    state=call(client,session,"/api/ledger/state")
    assert state["balances"]["wallet"]==300400
    assert all(state["checks"].values())
    assert all(r["status"]=="matched" for r in state["reconciliation"])


def test_java_engine_is_real_isolated_and_replayable(client):
    a,b=fresh(),fresh()
    result=call(client,a,"/api/market/orders",{"id":"order1","side":"buy","type":"market","quantity":50})
    assert result["state"]["position"]==150
    assert call(client,b,"/api/market/state")["state"]["position"]==100
    call(client,a,"/api/market/step",{"ticks":10})
    before=call(client,a,"/api/market/state")["state"]
    replay=call(client,a,"/api/market/replay",{})
    assert replay["result"]["identical"]
    assert replay["state"]==before
    assert all(before["checks"].values())


def test_public_invalid_command_cannot_escape_sandbox(client):
    for path in ["/api/market/orders/x\nRESET/cancel", "/etc/passwd", "/api/ledger/state/../../secret"]:
        response=client.post("/api/demo",json={"path":path,"body":{},"session":fresh()})
        assert response.status_code==409


def test_public_workload_and_payload_caps(client):
    session=fresh()
    for _ in range(11):
        session["history"].append({"path":"/api/market/step","body":{"ticks":100},"at":session["started_at"],"nonce":"01234567"})
    assert client.post("/api/demo",json={"path":"/api/market/state","session":session}).status_code==409
    assert client.post("/api/demo",content=b"x"*100001).status_code==413


def test_liquidity_reset_starts_a_new_transcript(client):
    session=fresh()
    call(client,session,"/api/market/orders",{"id":"o1","side":"buy","type":"market","quantity":50})
    value=call(client,session,"/api/market/reset",{"liquidity":"thin"})
    assert len(session["history"])==1
    assert value["state"]["position"]==100
    value=call(client,session,"/api/market/orders",{"id":"o2","side":"buy","type":"market","quantity":50})
    assert value["result"]["filled"]==45
