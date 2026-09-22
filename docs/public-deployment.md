# Public deployment

The deployment runs the same Python ledger and Java matching engine as the local
projects. Vercel hosts FastAPI; the build downloads a checksum-pinned Temurin JDK,
compiles `MarketEngine.java`, and uses `jlink` to bundle only Java's base module.
There is no client-side substitute for the financial engines.

## Isolated public sessions

Anonymous visitors must not share a wallet or market account. In public mode,
the browser stores a bounded command transcript in `sessionStorage`, independently
for each project and tab. Each request sends that transcript to `/api/demo`.

- ClearLedger rebuilds a temporary SQLite database and applies the commands with
  stable timestamps and posting IDs, using the original ledger service.
- MarketLab executes a validated command batch in a fresh, memory-bounded Java
  process and returns the resulting snapshot. Intermediate snapshots are omitted
  from transport to avoid quadratic response volume.
- The accepted command is returned with the response and added to that tab's transcript.
  A second visitor cannot change it. Cold starts do not depend on previous server state.
- **New session** resets only the selected project's transcript in that tab.

This hosting adapter is a **replayable public sandbox**, not a durable hosted ledger.
Closing/clearing the tab discards its transcript. Public demo state is intentionally
visitor-controlled and is not an authenticated financial record. The local SQLite
application remains available for durable recovery and concurrency experiments.

## Resource and routing boundaries

Public requests are limited to 100 KB, 200 commands per project transcript, and
1,000 market ticks. Java runs with a 128 MB heap and a 12-second process timeout.
Only allowlisted operations and validated typed payloads are executed; no shell
commands or user-provided file paths are accepted. The shared local mutation
endpoints are not registered in public mode.

The hosted mode is enabled by `PUBLIC_DEMO=1` or `VERCEL=1`. It requires no database,
market-data credentials, or payment keys. The function source bundle excludes local
databases, environment files, and development screenshots.

## Deploy and verify

```bash
vercel deploy --prod --yes --project fintech-engineering-lab
python scripts/check_public_browser.py --url YOUR_PUBLIC_ORIGIN
```

Verify using an ordinary unauthenticated browser or HTTP request, not a Vercel
authentication-bypass token. The public-browser check uses two fresh browser contexts
and checks ledger isolation, recovery, real Java execution, replay, and resets.

To exercise the same adapter locally:

```bash
PUBLIC_DEMO=1 python -m uvicorn app:app --host 127.0.0.1 --port 8765
```
