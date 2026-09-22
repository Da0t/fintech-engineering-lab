# Portfolio positioning and resume copy

These projects extend Dat Nguyen's existing experience with streaming dashboards,
deterministic replay, SQL, deduplication, and simulation into financial systems.
ClearLedger adds transaction correctness; MarketLab adds Java and market mechanics.

## Suggested replacement entries

Use after reviewing the code and being able to explain the design. These bullets
describe the implemented local prototypes; they do not claim real customers,
production deployment, live exchange connectivity, or PostgreSQL.

**ClearLedger: Financial Reconciliation Platform | Python, FastAPI, SQLite, JavaScript**

- Built an append-only transfer ledger with integer-cent accounting, protected balances,
  funds reservations, and bounded partial refunds using atomic SQLite transactions.
- Implemented a durable event inbox with payload-aware idempotency and interrupted-worker
  recovery; verified one posting for 100 events about the same payment processed across 8 worker threads.
- Developed an operations dashboard comparing internal postings with independent simulated
  provider records, surfacing missing transactions and amount mismatches with an auditable event trail.

**MarketLab: Market Replay & Execution Simulator | Java, Python, FastAPI, JavaScript**

- Built a Java price/time-priority matching engine supporting limit and market orders,
  partial fills, cancellation, conservative buying-power reservations, and per-fill fees.
- Implemented deterministic command replay, reconstructing identical order-book, fill,
  cash, and position state after a 400-command synthetic trading session.
- Created an interactive execution dashboard to compare synthetic liquidity scenarios,
  attribute execution costs, and demonstrate stale-feed order blocking and snapshot recovery.

## Interview points worth understanding

### ClearLedger

1. Why do paired transfers guarantee a balanced journal but not automatically prevent overspending?
2. What race does `BEGIN IMMEDIATE` prevent, and what throughput tradeoff does it introduce?
3. Why distinguish event identity from payment identity?
4. What happens if a process fails after the journal INSERT but before transaction commit?
5. Why does local idempotency not imply exactly-once delivery to a real external provider?
6. How would account-level locking, an outbox, and provider signatures change a production design?

### MarketLab

1. Why use a sorted map of FIFO queues rather than sorting every incoming order?
2. Why do fills use resting-order prices, and why must a market remainder not rest?
3. Why reserve fees per share conservatively instead of assuming a single fill?
4. What information belongs in deterministic state, and why exclude timing measurements?
5. How does preflight prevent a rejected self-trade from partially changing the account?
6. Why does this synthetic liquidity model not predict actual market impact?

## Using the measured evidence

`artifacts/benchmark.json` contains the exact recorded workload, machine/runtime details,
latencies, replay comparison, and duplicate-payment results. Read its scope fields before
using a number. Prefer correctness evidence over decontextualized microsecond claims.

Keep Pylon on the resume until you can independently walk through MarketLab's matching
and reservation code. Replace Perch with ClearLedger first; your internships already
provide substantial evidence of general full-stack development.

The original resume PDF is unchanged. This file is suggested replacement text, not an
assertion that the projects were built before this session or used in production.
