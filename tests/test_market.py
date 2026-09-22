import pytest
from marketlab.bridge import Market, MarketError


@pytest.fixture
def market():
    market = Market()
    yield market
    market.close()


def sound(result):
    assert all(result["state"]["checks"].values()), result["state"]["checks"]
    return result["state"]


def test_market_buy_accounts_for_price_and_fees(market):
    result = market.command("ORDER\tbuy1\tbuy\tmarket\t50\t10000")
    state = sound(result)
    assert result["result"]["filled"] == 50
    assert state["position"] == 150
    assert state["cash"] == 10_000_000 - 50*10002 - 501
    assert state["fees"] == 501


def test_thin_liquidity_partial_fill_and_slippage(market):
    market.command("RESET\tthin")
    result = market.command("ORDER\tlarge\tbuy\tmarket\t100\t10000")
    state = sound(result)
    fills = result["result"]["fills"]
    assert 0 < result["result"]["filled"] < 100
    assert len(fills) == 8
    assert fills[-1]["price"] > fills[0]["price"]
    assert state["orders"] == []  # unfilled market remainder never rests


def test_limit_reservation_and_cancel(market):
    result = market.command("ORDER\tlimit1\tbuy\tlimit\t100\t9900")
    state = sound(result)
    assert state["reserved_cash"] == 991000
    assert state["available_cash"] == 9_009_000
    result = market.command("CANCEL\tlimit1")
    assert sound(result)["reserved_cash"] == 0
    assert result["state"]["available_cash"] == 10_000_000


def test_resting_orders_fill_on_tick_and_reservations_reconcile(market):
    market.command("ORDER\tlimit1\tbuy\tlimit\t20\t9995")
    result = market.command("STEP\t50")
    state = sound(result)
    assert any(f["order_id"] == "limit1" for f in state["fills"])
    assert state["reserved_cash"] == 0


def test_price_time_priority(market):
    market.command("ORDER\tfirst\tbuy\tlimit\t200\t9995")
    market.command("ORDER\tsecond\tbuy\tlimit\t200\t9995")
    result = market.command("STEP\t50")
    fills = result["state"]["fills"]
    ids = [f["order_id"] for f in fills]
    assert ids.index("first") < ids.index("second")
    second_index = ids.index("second")
    assert sum(f["quantity"] for f in fills[:second_index] if f["order_id"] == "first") == 200
    sound(result)


def test_duplicate_order_is_idempotent_conflict_rejected(market):
    market.command("ORDER\tx\tbuy\tmarket\t10\t10000")
    result = market.command("ORDER\tx\tbuy\tmarket\t10\t10000")
    assert result["result"]["duplicate"] is True
    assert sound(result)["position"] == 110
    with pytest.raises(MarketError, match="different payload"):
        market.command("ORDER\tx\tbuy\tmarket\t11\t10000")


def test_buying_power_oversell_and_self_trade_rejections(market):
    with pytest.raises(MarketError, match="buying power"):
        market.command("ORDER\tlarge\tbuy\tlimit\t10000\t10000")
    with pytest.raises(MarketError, match="available shares"):
        market.command("ORDER\tshort\tsell\tmarket\t101\t10000")
    market.command("ORDER\tsell\tsell\tlimit\t50\t10001")
    with pytest.raises(MarketError, match="self-trade"):
        market.command("ORDER\tbuy\tbuy\tmarket\t10\t10000")
    state = sound(market.command("STATE"))
    assert state["cash"] == 10_000_000
    assert state["available_position"] == 50


def test_feed_gap_blocks_orders_then_recovers(market):
    market.command("DISCONNECT")
    result = market.command("STEP\t10")
    assert result["state"]["feed_tick"] == 0
    assert result["state"]["tick"] == 10
    with pytest.raises(MarketError, match="disconnected"):
        market.command("ORDER\tblocked\tbuy\tmarket\t1\t10000")
    result = market.command("RECONNECT")
    assert result["result"]["gap"] == 10
    assert sound(result)["feed_tick"] == 10


def test_full_replay_identical_after_fills_cancels_and_gap(market):
    for command in ["RESET\tthin", "ORDER\ta\tbuy\tmarket\t20\t10000", "STEP\t10", "ORDER\tb\tbuy\tlimit\t5\t9800", "CANCEL\tb", "DISCONNECT", "STEP\t10", "RECONNECT", "ORDER\tc\tsell\tmarket\t10\t10000"]:
        market.command(command)
    before = market.command("STATE")["state"]
    result = market.command("REPLAY")
    assert result["result"]["identical"]
    assert result["state"] == before
    sound(result)


def test_long_session_invariants(market):
    for i in range(100):
        sound(market.command(f"ORDER\torder{i}\t{'buy' if i%2==0 else 'sell'}\tmarket\t5\t10000"))
        sound(market.command("STEP\t1"))
    assert market.command("REPLAY")["result"]["identical"]
