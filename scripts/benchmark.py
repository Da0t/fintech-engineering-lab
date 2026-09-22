"""Reproducible local measurements, never a production capacity claim."""
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clearledger.ledger import Ledger
from marketlab.bridge import Market


def percentile(values, p):
    values = sorted(values)
    return round(values[min(len(values)-1, int((len(values)-1)*p))], 3)


def main():
    with tempfile.TemporaryDirectory() as directory:
        ledger = Ledger(Path(directory)/"bench.sqlite")
        latencies = []
        started = perf_counter()
        for i in range(200):
            t = perf_counter()
            ledger.receive(f"evt_{i}", f"pay_{i}", 10000)
            ledger.process(f"evt_{i}")
            latencies.append((perf_counter()-t)*1000)
        duration = perf_counter()-started
        for i in range(100):
            ledger.receive(f"duplicate_{i}", "same-payment", 12900)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(ledger.process, [f"duplicate_{i}" for i in range(100)]))
        state = ledger.snapshot()
        with ledger.connect() as db:
            actual = db.execute("SELECT COUNT(*) FROM journal WHERE reference='same-payment'").fetchone()[0]
        ledger_result = {
            "workload":"200 sequential receive+process operations; 100 additional event IDs for one payment processed with 8 threads",
            "unique_deposits":200,"duration_seconds":round(duration,3),
            "operations_per_second":round(200/duration,2),
            "receive_and_process_p50_ms":round(statistics.median(latencies),3),
            "receive_and_process_p95_ms":percentile(latencies,.95),
            "concurrent_duplicate_events":100,"actual_duplicate_payment_postings":actual,
            "invariants":state["checks"],
            "scope":"SQLite WAL on this host; includes Python service and DB transactions; excludes HTTP and browser"
        }
    market = Market()
    try:
        # JVM warm-up uses the same alternating buy/sell workload as the measurement.
        for i in range(100):
            market.command(f"ORDER\twarm{i}\t{'buy' if i%2==0 else 'sell'}\tmarket\t5\t10000")
            market.command("STEP\t1")
        market.command("RESET\tliquid")
        engine_times, roundtrips = [], []
        for i in range(200):
            started=perf_counter()
            result=market.command(f"ORDER\tbench{i}\t{'buy' if i%2==0 else 'sell'}\tmarket\t5\t10000")
            roundtrips.append((perf_counter()-started)*1000)
            engine_times.append(result["engine_micros"])
            market.command("STEP\t1")
        replay=market.command("REPLAY")
        market_result={
            "workload":"100 warm-up orders, then 200 alternating 5-share market orders; 1 synthetic tick between orders",
            "orders":200,"engine_p50_microseconds":round(statistics.median(engine_times),3),
            "engine_p95_microseconds":percentile(engine_times,.95),
            "bridge_roundtrip_p95_ms":percentile(roundtrips,.95),
            "replayed_commands":replay["result"]["commands_replayed"],
            "replay_identical":replay["result"]["identical"],"invariants":replay["state"]["checks"],
            "scope":"Single Java process, one symbol, synthetic depth; engine timer includes command handling but excludes snapshot serialization, IPC, HTTP, and browser. Not a JMH benchmark."
        }
        scenarios={}
        for mode in ["liquid","thin"]:
            market.command("RESET\t"+mode)
            result=market.command("ORDER\tcomparison\tbuy\tmarket\t50\t10000")["result"]
            fills=result["fills"]
            qty=sum(f["quantity"] for f in fills)
            scenarios[mode]={"requested":50,"filled":qty,"fill_count":len(fills),
                "average_price_cents":round(sum(f["price"]*f["quantity"] for f in fills)/qty,4),
                "fees_cents":sum(f["fee"] for f in fills)}
        market_result["liquidity_comparison"]=scenarios
    finally:
        market.close()
    report={"recorded_at":datetime.now(timezone.utc).isoformat(),
        "environment":{"platform":platform.platform(),"machine":platform.machine(),"logical_cpus":os.cpu_count(),
            "python":platform.python_version(),"java":subprocess.run(["java","-version"],capture_output=True,text=True).stderr.splitlines()[0]},
        "clearledger":ledger_result,"marketlab":market_result}
    target=ROOT/"artifacts"/"benchmark.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
