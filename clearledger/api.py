import os
import threading
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt
from .ledger import Ledger, LedgerError, InjectedCrash

router = APIRouter(prefix="/api/ledger", tags=["ClearLedger"])
_ledger = None
_init_lock = threading.Lock()


def service():
    global _ledger
    with _init_lock:
        if _ledger is None:
            ledger = Ledger(os.environ.get("LEDGER_DB", str(Path(__file__).resolve().parents[1] / ".data" / "ledger.sqlite")))
            ledger.seed()
            _ledger = ledger
    return _ledger


def call(action):
    try:
        return action()
    except (LedgerError, InjectedCrash) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class Event(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    payment_id: str = Field(min_length=1, max_length=100)
    amount: StrictInt = Field(gt=0, le=100_000_000)


class Refund(BaseModel):
    payment_id: str = Field(min_length=1, max_length=100)
    amount: StrictInt = Field(gt=0, le=100_000_000)
    key: str = Field(min_length=1, max_length=100)


class Hold(BaseModel):
    hold_id: str = Field(min_length=1, max_length=100)
    amount: StrictInt = Field(gt=0, le=100_000_000)


class Resolve(BaseModel):
    action: str
    key: str = Field(min_length=1, max_length=100)


class Provider(BaseModel):
    record_id: str = Field(min_length=1, max_length=100)
    payment_id: str = Field(min_length=1, max_length=100)
    kind: str
    amount: StrictInt = Field(gt=0, le=100_000_000)


@router.get("/state")
def state():
    return service().snapshot()


@router.post("/incident")
def incident():
    return call(lambda: service().incident())


@router.post("/events")
def receive(body: Event):
    return call(lambda: service().receive(body.event_id, body.payment_id, body.amount))


@router.post("/events/{event_id}/retry")
def retry(event_id: str):
    return call(lambda: service().process(event_id))


@router.post("/refunds")
def refund(body: Refund):
    return call(lambda: service().refund(body.payment_id, body.amount, body.key))


@router.post("/holds")
def hold(body: Hold):
    return call(lambda: service().hold(body.hold_id, body.amount))


@router.post("/holds/{hold_id}/resolve")
def resolve(hold_id: str, body: Resolve):
    return call(lambda: service().resolve_hold(hold_id, body.action, body.key))


@router.post("/provider-records")
def provider(body: Provider):
    return call(lambda: service().import_provider(body.record_id, body.payment_id, body.kind, body.amount))
