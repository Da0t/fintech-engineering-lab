"""SQLite ledger with balanced-by-construction postings and a durable event inbox.

Every journal row transfers a positive integer amount between two accounts. The
entries view expands it into equal negative/positive legs, so unbalanced journals
cannot be represented. BEGIN IMMEDIATE serializes balance checks and writes.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class LedgerError(ValueError):
    pass


class InjectedCrash(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Ledger:
    def __init__(self, path, clock=now, id_factory=uuid4):
        self.path = str(path)
        self.clock = clock
        self.id_factory = id_factory
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, protected INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS commands (
                key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS journal (
                id TEXT PRIMARY KEY, operation TEXT NOT NULL, kind TEXT NOT NULL,
                debit TEXT NOT NULL REFERENCES accounts(id),
                credit TEXT NOT NULL REFERENCES accounts(id),
                amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND amount > 0),
                reference TEXT NOT NULL, created_at TEXT NOT NULL,
                CHECK(debit != credit));
            CREATE VIEW IF NOT EXISTS entries AS
                SELECT id, operation, debit AS account, -amount AS delta FROM journal
                UNION ALL SELECT id, operation, credit AS account, amount AS delta FROM journal;
            CREATE INDEX IF NOT EXISTS journal_debit ON journal(debit);
            CREATE INDEX IF NOT EXISTS journal_credit ON journal(credit);
            CREATE INDEX IF NOT EXISTS journal_reference ON journal(reference,kind);
            CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
                BEGIN SELECT RAISE(ABORT, 'Journal is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
                BEGIN SELECT RAISE(ABORT, 'Journal is immutable'); END;
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY, amount INTEGER NOT NULL, refunded INTEGER NOT NULL DEFAULT 0,
                CHECK(refunded >= 0 AND refunded <= amount));
            CREATE TABLE IF NOT EXISTS holds (
                id TEXT PRIMARY KEY, amount INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('reserved','settled','released')));
            CREATE TABLE IF NOT EXISTS inbox (
                id TEXT PRIMARY KEY, payment_id TEXT NOT NULL, amount INTEGER NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT, received_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS provider_records (
                id TEXT PRIMARY KEY, payment_id TEXT NOT NULL, kind TEXT NOT NULL,
                amount INTEGER NOT NULL, imported_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
                reference TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            db.executemany("INSERT OR IGNORE INTO accounts VALUES (?,?,?)", [
                ("wallet", "Available wallet", 1), ("reserved", "Reserved funds", 1),
                ("clearing", "Provider clearing", 0), ("merchant", "Merchant settlement", 0)])

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @contextmanager
    def atomic(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def amount(value):
        if type(value) is not int or not 0 < value <= 100_000_000:
            raise LedgerError("Amount must be an integer from 1 to 100,000,000 cents")

    @staticmethod
    def balance(db, account):
        return db.execute("SELECT COALESCE(SUM(delta),0) FROM entries WHERE account=?", (account,)).fetchone()[0]

    def audit(self, db, action, reference, detail):
        db.execute("INSERT INTO audit(action,reference,detail,created_at) VALUES (?,?,?,?)", (action, reference, detail, self.clock()))

    def post(self, db, operation, kind, debit, credit, amount, reference):
        self.amount(amount)
        protected = db.execute("SELECT protected FROM accounts WHERE id=?", (debit,)).fetchone()
        if protected and protected[0] and self.balance(db, debit) < amount:
            raise LedgerError("Insufficient available funds")
        db.execute("INSERT INTO journal VALUES (?,?,?,?,?,?,?,?)", (str(self.id_factory()), operation, kind, debit, credit, amount, reference, self.clock()))

    def command(self, db, key, payload, perform):
        if not key or len(key) > 160:
            raise LedgerError("An idempotency key of 1–160 characters is required")
        digest = fingerprint(payload)
        previous = db.execute("SELECT * FROM commands WHERE key=?", (key,)).fetchone()
        if previous:
            if previous["fingerprint"] != digest:
                raise LedgerError("Idempotency key was already used for a different request")
            return {**json.loads(previous["result"]), "duplicate": True}
        result = perform()
        db.execute("INSERT INTO commands VALUES (?,?,?)", (key, digest, json.dumps(result)))
        return {**result, "duplicate": False}

    def receive(self, event_id, payment_id, amount):
        self.amount(amount)
        if not event_id or not payment_id:
            raise LedgerError("Event and payment IDs are required")
        with self.atomic() as db:
            previous = db.execute("SELECT * FROM inbox WHERE id=?", (event_id,)).fetchone()
            if previous:
                if previous["payment_id"] != payment_id or previous["amount"] != amount:
                    raise LedgerError("Event ID was already used with a different payload")
                self.audit(db, "duplicate delivery", event_id, "Inbox deduplicated the repeated event")
                return {"duplicate": True, "event_id": event_id}
            db.execute("INSERT INTO inbox VALUES (?,?,?,'pending',0,NULL,?)", (event_id, payment_id, amount, self.clock()))
            self.audit(db, "event received", payment_id, f"{event_id} queued durably")
            return {"duplicate": False, "event_id": event_id}

    def process(self, event_id, crash=False):
        # The attempt is durable. A crash here leaves a recoverable pending event.
        with self.atomic() as db:
            event = db.execute("SELECT * FROM inbox WHERE id=?", (event_id,)).fetchone()
            if not event:
                raise LedgerError("Unknown event")
            if event["status"] == "completed":
                return {"duplicate": True, "payment_id": event["payment_id"]}
            db.execute("UPDATE inbox SET attempts=attempts+1 WHERE id=?", (event_id,))
            if crash:
                db.execute("UPDATE inbox SET error='Injected worker crash before ledger commit' WHERE id=?", (event_id,))
                self.audit(db, "worker interrupted", event["payment_id"], "Attempt persisted; no funds posted. Safe to retry.")
        if crash:
            raise InjectedCrash("Worker interrupted before ledger commit; event remains pending")
        try:
            with self.atomic() as db:
                event = db.execute("SELECT * FROM inbox WHERE id=?", (event_id,)).fetchone()
                if event["status"] == "completed":
                    return {"duplicate": True, "payment_id": event["payment_id"]}
                def deposit():
                    self.post(db, "deposit:" + event["payment_id"], "deposit", "clearing", "wallet", event["amount"], event["payment_id"])
                    db.execute("INSERT INTO payments(id,amount) VALUES (?,?)", (event["payment_id"], event["amount"]))
                    return {"payment_id": event["payment_id"], "amount": event["amount"]}
                result = self.command(db, "deposit:" + event["payment_id"], {"kind": "deposit", "amount": event["amount"]}, deposit)
                db.execute("UPDATE inbox SET status='completed',error=NULL WHERE id=?", (event_id,))
                self.audit(db, "payment deduplicated" if result["duplicate"] else "deposit posted", event["payment_id"], f"{event_id}: ledger and inbox committed atomically")
                return result
        except LedgerError as exc:
            with self.atomic() as db:
                db.execute("UPDATE inbox SET status='failed',error=? WHERE id=?", (str(exc), event_id))
                self.audit(db, "event rejected", event["payment_id"], str(exc))
            raise

    def refund(self, payment_id, amount, key):
        self.amount(amount)
        with self.atomic() as db:
            def perform():
                payment = db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
                if not payment:
                    raise LedgerError("Unknown payment")
                if payment["refunded"] + amount > payment["amount"]:
                    raise LedgerError("Refund exceeds the original payment's remaining refundable amount")
                self.post(db, key, "refund", "wallet", "clearing", amount, payment_id)
                db.execute("UPDATE payments SET refunded=refunded+? WHERE id=?", (amount, payment_id))
                self.audit(db, "refund posted", payment_id, f"{amount} cents; original posting preserved")
                return {"payment_id": payment_id, "amount": amount, "operation": key}
            return self.command(db, "refund:" + key, {"kind": "refund", "payment_id": payment_id, "amount": amount}, perform)

    def hold(self, hold_id, amount):
        self.amount(amount)
        with self.atomic() as db:
            def perform():
                self.post(db, "hold:" + hold_id, "reserve", "wallet", "reserved", amount, hold_id)
                db.execute("INSERT INTO holds VALUES (?,?,'reserved')", (hold_id, amount))
                self.audit(db, "funds reserved", hold_id, f"{amount} cents removed from available balance")
                return {"hold_id": hold_id, "amount": amount}
            return self.command(db, "hold:" + hold_id, {"kind": "hold", "amount": amount}, perform)

    def resolve_hold(self, hold_id, action, key):
        if action not in ("settle", "release"):
            raise LedgerError("Action must be settle or release")
        with self.atomic() as db:
            def perform():
                hold = db.execute("SELECT * FROM holds WHERE id=?", (hold_id,)).fetchone()
                if not hold or hold["state"] != "reserved":
                    raise LedgerError("Hold is not reserved")
                self.post(db, key, action, "reserved", "merchant" if action == "settle" else "wallet", hold["amount"], hold_id)
                db.execute("UPDATE holds SET state=? WHERE id=?", ("settled" if action == "settle" else "released", hold_id))
                self.audit(db, "hold " + action, hold_id, f"{hold['amount']} cents moved atomically")
                return {"hold_id": hold_id, "action": action}
            return self.command(db, "resolve:" + key, {"hold_id": hold_id, "action": action}, perform)

    def import_provider(self, record_id, payment_id, kind, amount):
        self.amount(amount)
        if kind not in ("deposit", "refund"):
            raise LedgerError("Unsupported provider record type")
        with self.atomic() as db:
            previous = db.execute("SELECT * FROM provider_records WHERE id=?", (record_id,)).fetchone()
            if previous:
                if (previous["payment_id"], previous["kind"], previous["amount"]) != (payment_id, kind, amount):
                    raise LedgerError("Provider record ID has a conflicting payload")
                return {"duplicate": True}
            db.execute("INSERT INTO provider_records VALUES (?,?,?,?,?)", (record_id, payment_id, kind, amount, self.clock()))
            self.audit(db, "provider record imported", payment_id, f"{record_id}: {kind} {amount} cents")
            return {"duplicate": False}

    @staticmethod
    def reconciliation(db):
        internal = {(r["reference"], r["kind"]): r["amount"] for r in db.execute("SELECT reference,kind,SUM(amount) AS amount FROM journal WHERE kind IN ('deposit','refund') GROUP BY reference,kind")}
        external = {(r["payment_id"], r["kind"]): r["amount"] for r in db.execute("SELECT payment_id,kind,SUM(amount) AS amount FROM provider_records GROUP BY payment_id,kind")}
        rows = []
        for payment, kind in sorted(internal.keys() | external.keys()):
            local, remote = internal.get((payment, kind), 0), external.get((payment, kind), 0)
            status = "matched" if local == remote else "missing internally" if local == 0 else "missing at provider" if remote == 0 else "amount mismatch"
            rows.append({"payment_id": payment, "kind": kind, "internal": local, "provider": remote, "difference": local-remote, "status": status})
        return rows

    def snapshot(self):
        with self.connect() as db:
            db.execute("BEGIN")  # all widgets see the same consistent database snapshot
            balances = {row["id"]: self.balance(db, row["id"]) for row in db.execute("SELECT id FROM accounts")}
            holds = [dict(r) for r in db.execute("SELECT * FROM holds")]
            checks = {
                "balanced": sum(balances.values()) == 0,
                "nonnegative_wallet": balances["wallet"] >= 0,
                "holds_reconciled": balances["reserved"] == sum(h["amount"] for h in holds if h["state"] == "reserved"),
                "refunds_bounded": db.execute("SELECT COUNT(*) FROM payments WHERE refunded > amount OR refunded < 0").fetchone()[0] == 0,
            }
            return {"balances": balances, "checks": checks, "holds": holds,
                "payments": [dict(r) for r in db.execute("SELECT * FROM payments")],
                "journal": [dict(r) for r in db.execute("SELECT * FROM journal ORDER BY rowid DESC LIMIT 100")],
                "inbox": [dict(r) for r in db.execute("SELECT * FROM inbox ORDER BY rowid DESC LIMIT 100")],
                "audit": [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 100")],
                "reconciliation": self.reconciliation(db), "currency": "USD", "storage": "SQLite / WAL"}

    def seed(self):
        for payment_id, amount in [("pay_opening", 250000), ("pay_topup", 85000)]:
            self.receive("evt_" + payment_id, payment_id, amount)
            self.process("evt_" + payment_id)
            self.import_provider("statement_" + payment_id, payment_id, "deposit", amount)
        self.hold("entry_001", 45000)

    def incident(self, suffix=None):
        suffix = suffix or uuid4().hex[:8]
        payment, event = "pay_" + suffix, "evt_" + suffix
        self.import_provider("statement_" + suffix, payment, "deposit", 12900)
        self.receive(event, payment, 12900)
        for _ in range(2):
            self.receive(event, payment, 12900)
        try:
            self.process(event, crash=True)
        except InjectedCrash:
            pass
        return {"payment_id": payment, "event_id": event, "message": "Provider received $129.00. Three deliveries deduplicated; worker interrupted. Retry the pending event to reconcile."}
