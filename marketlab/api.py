from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt
from .bridge import Market, MarketError

router = APIRouter(prefix="/api/market", tags=["MarketLab"])
market = Market()


class Order(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"]
    quantity: StrictInt = Field(gt=0, le=10000)
    limit: StrictInt = Field(default=10000, gt=0, le=1000000)


class Step(BaseModel):
    ticks: StrictInt = Field(default=1, ge=1, le=100)


class Reset(BaseModel):
    liquidity: Literal["liquid", "thin"]


def send(command):
    try:
        return market.command(command)
    except MarketError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/state")
def state():
    return send("STATE")


@router.post("/orders")
def order(body: Order):
    return send(f"ORDER\t{body.id}\t{body.side}\t{body.type}\t{body.quantity}\t{body.limit}")


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: str):
    if not order_id.isascii() or not all(c.isalnum() or c in "_-" for c in order_id):
        raise HTTPException(422, "Invalid order ID")
    return send("CANCEL\t" + order_id)


@router.post("/step")
def step(body: Step):
    return send(f"STEP\t{body.ticks}")


@router.post("/reset")
def reset(body: Reset):
    return send("RESET\t" + body.liquidity)


@router.post("/replay")
def replay():
    return send("REPLAY")


@router.post("/feed/{action}")
def feed(action: Literal["disconnect", "reconnect"]):
    return send(action.upper())
