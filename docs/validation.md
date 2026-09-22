# Local validation — September 22, 2026

## Automated checks

Public-hosting update: **42 tests passed** after adding the isolated replay adapter.
The public-mode tests cover visitor isolation, stable ledger reconstruction,
incident recovery, Java execution and replay, request/workload limits, and session
resets. The first GitHub Actions run also passed on Linux with Java 17.
The original local-mode results below are retained as the baseline.

**7 production browser checks passed** at
https://fintech-engineering-lab.vercel.app using two fresh, unauthenticated browser
contexts. They verified desktop/mobile access, isolated ledger state, payment
recovery, Java execution and replay, thin-book partial fills, and project-local
resets, with no browser JavaScript exceptions. The exact checks are recorded in
[`public-browser-check.json`](../artifacts/public-browser-check.json).

- **35 tests passed** with `python3 -m pytest -q --tb=short`.
- Coverage includes concurrent deposits and reservations, duplicate identities,
  conflicting payloads, refund limits, rollback after journal insertion, durable
  recovery, immutable journal rows, reconciliation mismatches, price/time priority,
  partial fills, buying-power reservations, self-trade prevention, stale feed
  rejection, deterministic replay, and API input validation.
- **10 browser workflow/layout checks passed**, covering both actual interfaces,
  with zero JavaScript exceptions at desktop and mobile sizes. See
  [`browser-check.json`](../artifacts/browser-check.json) for the check list.
- Screenshots were rendered and inspected at 1440px desktop and 390px mobile width.
  Tables scroll inside their containers on narrow viewports.
- GitHub Actions configuration is included, but no remote CI run is claimed.

## Measured correctness evidence

The benchmark ran on macOS arm64 with Python 3.13.1 and OpenJDK 24.0.1.
Exact data and timing boundaries are in [`benchmark.json`](../artifacts/benchmark.json).

| Experiment | Observed result |
| --- | --- |
| 100 distinct delivery IDs for one payment, processed with 8 threads | Exactly 1 payment posting |
| 200 market orders interleaved with 200 price ticks | All 5 engine invariants passed |
| Replay those 400 accepted commands | Complete state identical |
| 50-share buy, liquid book at tick 0 | 50 shares filled at $100.02 average |
| Same requested quantity, thin book at tick 0 | 45 shares filled across 8 levels at $100.662 average; 5 cancelled |

The local timing report distinguishes ledger-service latency from Java command
handling and Python/Java round-trip latency. It is intentionally not promoted as
production throughput or a comparison with commercial exchanges.

## Important boundaries

The demos use synthetic data, SQLite, HTTP, and a dependency-free JavaScript UI.
There is no live trading, real payments integration, PostgreSQL deployment, React
frontend, user authentication, or multi-user isolation. Market state is in memory;
ledger state persists locally. Those are documented scope limits, not tested features.
