# ClearLedger

An inspectable, single-currency ledger with recovery and reconciliation workflows.
Run from the repository root using the [launcher instructions](../README.md).

## Financial model

All amounts are positive integer USD cents at input. A journal row represents a
transfer from a debit account to a credit account; the `entries` view expands it
into equal signed legs. The sum across all accounts is therefore zero by construction.
SQLite CHECK constraints reject zero, negative, non-integer, or self-transfers.
UPDATE/DELETE triggers prevent changing existing journal rows.

This is a transfer ledger using signed balances, not a complete general ledger with
asset/liability classifications. In particular, a negative `clearing` balance is
the offset for incoming customer funds, not a negative customer balance.

| Operation | Debit | Credit |
| --- | --- | --- |
| Deposit | Provider clearing | Available wallet |
| Reserve | Available wallet | Reserved funds |
| Release | Reserved funds | Available wallet |
| Settle | Reserved funds | Merchant settlement |
| Refund | Available wallet | Provider clearing |

## Correctness boundaries

- The service checks protected balances and inserts postings inside `BEGIN IMMEDIATE`.
  Concurrent local requests cannot both spend the same available funds.
- An idempotency key maps to a canonical request fingerprint and stored result.
  Repeating the request returns its result. Reusing the key with another payload fails.
- Event delivery IDs and economic payment IDs are deduplicated separately. Distinct
  events about the same payment can complete without posting it again.
- An inbox attempt is recorded before processing. The payment journal, payment record,
  idempotency result, and completed inbox status then commit in one transaction.
  Tests cover interruptions before posting and rollback after the journal INSERT.
- Refund totals cannot exceed the original deposit, and reserved money cannot fund a refund.
- An active reservation transitions once to settled or released. A refund or release
  is a new transfer; the original transfer is retained.

The database serializes writers; it is intentionally not a distributed “exactly-once
delivery” claim. It provides idempotent economic effects under repeated local delivery.
There are no real external side effects in this prototype. A payment-provider integration
would additionally need an outbox, provider-side idempotency, and authenticated webhooks.

## Independent reconciliation

Provider records are stored separately from the internal ledger and grouped by payment
ID and deposit/refund type. Comparison reports matched records, missing internal records,
missing provider records, and amount mismatches. Importing the same statement-record ID
is idempotent; a changed payload under that ID is rejected.

Refund acknowledgments are explicitly simulated by a separate user action. They are
not silently manufactured by reconciliation to make a mismatch disappear.

## API examples

```bash
curl http://127.0.0.1:8765/api/ledger/state
curl -X POST http://127.0.0.1:8765/api/ledger/incident
```

Use the incident response's event ID in `POST /api/ledger/events/{event_id}/retry`.
See `/docs` for deposit, refund, hold, settlement, and provider import request schemas.

## Limits

One synthetic wallet, USD only, one host, no real provider, no credentials or multi-tenant
authorization. The “worker crash” button injects an exception at a documented boundary;
it does not kill an OS process. A test reopens the database to verify durable recovery.
The UI shows the latest 100 journal rows, inbox events, and audit entries; reconciliation
and balance checks use all records. Reconciliation groups refunds at payment level,
so equal-and-opposite errors within a group need finer provider identifiers to detect.
