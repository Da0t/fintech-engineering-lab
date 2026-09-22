# MarketLab

A Java order-matching simulator with a browser execution inspector.
Run from the repository root using the [launcher instructions](../README.md).

## Matching and account state

`MarketEngine.java` uses sorted price levels (`TreeMap`) with a FIFO queue at each
level (`ArrayDeque`). An incoming order consumes the opposite side at resting-order
prices. Limit remainders rest on the book; market remainders are cancelled.

- One synthetic instrument, NOVA; whole shares and integer price cents.
- Initial paper account: $100,000 cash and 100 shares.
- Fees: 10 basis points of each fill's notional, rounded up to the next cent.
- Buy limits reserve `quantity × (limit price + per-share rounded fee)`. This is
  conservative enough to cover fragmented fills; unused reservation is released.
- Sell orders reserve holdings. No leverage, borrowing, or short selling.
- An order ID is bound to its request; retries do not execute it again. Conflicting
  reuse is rejected. Self-trades are rejected during preflight before any fills occur.

## Synthetic liquidity

Each tick follows a fixed price path. The market maker replaces its remaining external
orders with eight deterministic levels on either side, preserving the user's resting
orders. Fresh external orders may execute against those user orders. Liquid and thin
presets differ in quantity and distance between levels.

This is a controlled comparison, not a historical exchange simulator. External volume
refreshes mechanically, and executing an order does not permanently alter the future
synthetic price path. Execution costs are illustrative, not predictions of real trading.

## Replay

Every accepted mutating command is logged in process memory. **Verify replay** creates
a fresh engine with the same preset, applies the log, and compares the serialized
domain state, including book, open orders, fills, cash, positions, prices, and events.
The log is not durable across server restarts. Wall-clock timings are excluded from
the comparison because they are not deterministic domain state.

## Feed failure

Disconnecting leaves the last book visible and blocks new orders. Synthetic reference
ticks can still advance, making the gap observable. Reconnection replaces external
liquidity with the latest snapshot and resumes matching. This is a simulator behavior,
not a real exchange's outage policy. Cancelling your resting orders remains possible.

## Transport and performance

FastAPI sends tab-delimited validated commands over stdin to one persistent Java
process. Java responds with JSON on stdout. A Python lock serializes commands. The
browser calls HTTP endpoints; there is no live WebSocket connection.

The engine timer measures command handling before snapshot generation and JSON encoding.
The benchmark also reports the Python/Java round-trip separately. It uses a tiny,
single-symbol workload, not JMH or a load test. Do not describe the measured numbers
as exchange-scale throughput or end-user latency.

## Limits

500 user orders and 5,000 ticks per local session; reset to start another. One shared
account, one Java process, no persistence, no venue routing, no real market data,
and no authentication. Changing liquidity resets all market state. A dead engine
requires restarting the server rather than silently discarding and recreating state.
