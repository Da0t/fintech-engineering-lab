from concurrent.futures import ThreadPoolExecutor
import sqlite3
import pytest
from clearledger.ledger import Ledger, LedgerError, InjectedCrash


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.sqlite")


def deposit(ledger, amount=10000, payment="p1", event="e1"):
    ledger.receive(event, payment, amount)
    return ledger.process(event)


def assert_sound(ledger):
    snapshot = ledger.snapshot()
    assert all(snapshot["checks"].values()), snapshot["checks"]
    return snapshot


def test_duplicate_deliveries_and_distinct_events_for_same_payment(ledger):
    for _ in range(100):
        ledger.receive("event", "payment", 12900)
    for _ in range(10):
        ledger.process("event")
    deposit(ledger, 12900, "payment", "other-event")
    snapshot = assert_sound(ledger)
    assert snapshot["balances"]["wallet"] == 12900
    assert len(snapshot["journal"]) == 1


def test_crash_before_commit_survives_restart(ledger):
    ledger.receive("event", "payment", 12900)
    with pytest.raises(InjectedCrash):
        ledger.process("event", crash=True)
    assert ledger.snapshot()["balances"]["wallet"] == 0
    restarted = Ledger(ledger.path)
    restarted.process("event")
    state = assert_sound(restarted)
    assert state["balances"]["wallet"] == 12900
    assert state["inbox"][0]["attempts"] == 2
    assert state["inbox"][0]["status"] == "completed"


def test_rollback_after_journal_insert_before_inbox_commit(ledger, monkeypatch):
    ledger.receive("event", "payment", 12900)
    original = ledger.post
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("process failure after INSERT")
    monkeypatch.setattr(ledger, "post", crash)
    with pytest.raises(RuntimeError):
        ledger.process("event")
    assert ledger.snapshot()["journal"] == []
    monkeypatch.setattr(ledger, "post", original)
    ledger.process("event")
    assert assert_sound(ledger)["balances"]["wallet"] == 12900


def test_concurrent_deposits_post_once(ledger):
    for i in range(16):
        ledger.receive(f"e{i}", "same-payment", 10000)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(ledger.process, [f"e{i}" for i in range(16)]))
    assert assert_sound(ledger)["balances"]["wallet"] == 10000
    assert len(ledger.snapshot()["journal"]) == 1


def test_concurrent_holds_cannot_overspend(ledger):
    deposit(ledger)
    def hold(i):
        try:
            ledger.hold(f"hold{i}", 6000)
            return True
        except LedgerError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(hold, range(20)))
    assert sum(results) == 1
    assert assert_sound(ledger)["balances"]["wallet"] == 4000


def test_refunds_bounded_and_idempotent(ledger):
    deposit(ledger)
    ledger.refund("p1", 6000, "refund1")
    assert ledger.refund("p1", 6000, "refund1")["duplicate"]
    with pytest.raises(LedgerError, match="different request"):
        ledger.refund("p1", 5000, "refund1")
    with pytest.raises(LedgerError, match="exceeds"):
        ledger.refund("p1", 5000, "refund2")
    ledger.refund("p1", 4000, "refund3")
    assert assert_sound(ledger)["balances"]["wallet"] == 0


def test_refund_cannot_spend_reserved_money(ledger):
    deposit(ledger)
    ledger.hold("h1", 9000)
    with pytest.raises(LedgerError, match="Insufficient"):
        ledger.refund("p1", 2000, "r1")
    assert assert_sound(ledger)["payments"][0]["refunded"] == 0


def test_hold_lifecycle_is_atomic_and_cannot_double_settle(ledger):
    deposit(ledger)
    ledger.hold("h1", 7000)
    ledger.resolve_hold("h1", "settle", "s1")
    assert ledger.resolve_hold("h1", "settle", "s1")["duplicate"]
    with pytest.raises(LedgerError, match="not reserved"):
        ledger.resolve_hold("h1", "release", "s2")
    state = assert_sound(ledger)
    assert state["balances"]["merchant"] == 7000
    assert state["balances"]["reserved"] == 0
    ledger.hold("h2", 2000)
    ledger.resolve_hold("h2", "release", "release2")
    assert assert_sound(ledger)["balances"]["wallet"] == 3000


def test_payload_conflicts_cannot_change_balances(ledger):
    deposit(ledger)
    with pytest.raises(LedgerError, match="different payload"):
        ledger.receive("e1", "p1", 99999)
    ledger.receive("e2", "p1", 99999)
    with pytest.raises(LedgerError, match="different request"):
        ledger.process("e2")
    assert assert_sound(ledger)["balances"]["wallet"] == 10000
    assert ledger.snapshot()["inbox"][0]["status"] == "failed"


def test_provider_reconciliation_detects_each_break_type(ledger):
    deposit(ledger)
    ledger.import_provider("statement1", "p1", "deposit", 9999)
    ledger.import_provider("statement2", "p2", "deposit", 4000)
    ledger.refund("p1", 1000, "refund")
    rows = {(r["payment_id"], r["kind"]):r for r in ledger.snapshot()["reconciliation"]}
    assert rows[("p1", "deposit")]["status"] == "amount mismatch"
    assert rows[("p2", "deposit")]["status"] == "missing internally"
    assert rows[("p1", "refund")]["status"] == "missing at provider"
    assert rows[("p1", "deposit")]["difference"] == 1
    ledger.import_provider("refund_statement", "p1", "refund", 1000)
    assert ledger.import_provider("refund_statement", "p1", "refund", 1000)["duplicate"]
    with pytest.raises(LedgerError, match="conflicting"):
        ledger.import_provider("refund_statement", "p1", "refund", 1001)


def test_complete_incident_recovery_refund_and_reconciliation(ledger):
    ledger.seed()
    incident = ledger.incident()
    assert len([r for r in ledger.snapshot()["reconciliation"] if r["status"] != "matched"]) == 1
    ledger.process(incident["event_id"])
    assert all(r["status"] == "matched" for r in ledger.snapshot()["reconciliation"])
    ledger.refund(incident["payment_id"], 2500, "r1")
    ledger.import_provider("refund1", incident["payment_id"], "refund", 2500)
    assert all(r["status"] == "matched" for r in assert_sound(ledger)["reconciliation"])


@pytest.mark.parametrize("amount", [0,-1,1.5,True,"100",100_000_001])
def test_invalid_amounts(ledger, amount):
    with pytest.raises(LedgerError):
        ledger.receive("e", "p", amount)


def test_journal_is_immutable_at_database_level(ledger):
    deposit(ledger)
    with ledger.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE journal SET amount=99")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM journal")
    assert_sound(ledger)
