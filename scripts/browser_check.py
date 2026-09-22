"""Isolated end-to-end checks of the actual UI. Requires Playwright + Chromium."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "artifacts" / "screenshots"


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "LEDGER_DB": str(Path(temp)/"ui.sqlite")}
        log = open(Path(temp)/"server.log", "w+")
        server = subprocess.Popen([sys.executable,"-m","uvicorn","app:app","--host","127.0.0.1","--port",str(port)], cwd=ROOT, env=env, stdout=log, stderr=log)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    with urlopen(base+"/health", timeout=1):
                        break
                except Exception:
                    if server.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    time.sleep(.1)
            else:
                raise RuntimeError("Temporary UI server did not start")
            errors=[]
            checks=[]
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width":1440,"height":1060}, device_scale_factor=1)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base+"/clearledger")
                expect(page.get_by_role("heading", name="Every dollar. Accounted for.")).to_be_visible()
                expect(page.get_by_text("$2,900.00", exact=True)).to_be_visible()
                page.screenshot(path=SHOTS/"clearledger-desktop.png", full_page=True)
                page.get_by_role("button",name="Run failure scenario").click()
                expect(page.get_by_role("button",name="Retry event")).to_be_visible()
                page.screenshot(path=SHOTS/"clearledger-incident.png", full_page=True)
                page.get_by_role("button",name="Retry event").click()
                expect(page.get_by_text("$3,029.00",exact=True)).to_be_visible()
                expect(page.get_by_role("button",name="Retry event")).to_have_count(0)
                checks.append("duplicate-delivery / worker-recovery UI")
                page.get_by_role("button",name="Issue refund").click()
                page.get_by_label("Amount (USD)").fill("25.00")
                page.get_by_role("button",name="Post refund").click()
                expect(page.get_by_role("button",name="Simulate provider acknowledgment")).to_be_visible()
                page.get_by_role("button",name="Simulate provider acknowledgment").click()
                expect(page.get_by_text("$3,004.00",exact=True)).to_be_visible()
                checks.append("refund and independent provider acknowledgment")
                page.get_by_role("button",name="＋ Reserve",exact=True).click()
                page.get_by_label("Amount (USD)").fill("50.00")
                page.get_by_role("button",name="Reserve funds").click()
                expect(page.get_by_text("$2,954.00",exact=True)).to_be_visible()
                page.get_by_role("button",name="Release",exact=True).last.click()
                expect(page.get_by_text("$3,004.00",exact=True)).to_be_visible()
                page.get_by_role("button",name="Settle",exact=True).first.click()
                checks.append("reservation / release / settlement")
                page.get_by_role("button",name="Simulate deposit").click()
                page.get_by_label("Amount (USD)").fill("125.50")
                page.get_by_role("button",name="Process deposit").click()
                expect(page.get_by_text("$3,129.50",exact=True)).to_be_visible()
                checks.append("deposit form decimal conversion")
                page.get_by_role("link",name="MarketLab — execution and replay").click()
                expect(page.get_by_role("heading",name="The price is only the beginning.")).to_be_visible()
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.get_by_text("Order accepted. 50 of 50 shares filled immediately.")).to_be_visible()
                page.get_by_role("button",name="Thin",exact=True).click()
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.get_by_text("Order accepted. 45 of 50 shares filled immediately.")).to_be_visible()
                checks.append("liquid vs. thin order fills and cost breakdown")
                page.get_by_label("Order type").select_option("limit")
                page.get_by_label("Limit price (USD)").fill("98.00")
                page.get_by_label("Quantity (shares)").fill("5")
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.get_by_role("button",name="Cancel",exact=True)).to_be_visible()
                page.get_by_role("button",name="Cancel",exact=True).click()
                expect(page.get_by_role("button",name="Cancel",exact=True)).to_have_count(0)
                checks.append("limit order reservation and cancellation")
                page.get_by_role("button",name="Disconnect feed").click()
                page.get_by_role("button",name="+ 10 ticks").click()
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.get_by_text("Feed is disconnected. Reconnect before submitting orders.",exact=True)).to_be_visible()
                page.get_by_role("button",name="Reconnect feed").click()
                page.get_by_role("button",name="Verify replay").click()
                expect(page.locator("#toast")).to_contain_text("Replay verified")
                checks.append("feed-gap recovery and complete state replay")
                page.get_by_label("Order type").select_option("market")
                page.get_by_label("Quantity (shares)").fill("3")
                before = page.request.get(base+"/api/market/state").json()["state"]["position"]
                def lose_response(route):
                    route.fetch()  # The engine accepts the order; the browser never receives the response.
                    route.abort()
                page.route("**/api/market/orders", lose_response, times=1)
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.locator("#toast")).to_contain_text("Failed to fetch")
                assert page.request.get(base+"/api/market/state").json()["state"]["position"] == before+3
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.locator("#toast")).to_contain_text("Original order confirmed")
                assert page.request.get(base+"/api/market/state").json()["state"]["position"] == before+3
                checks.append("lost HTTP response retried without executing the trade twice")
                page.get_by_role("button",name="Liquid",exact=True).click()
                for _ in range(4):
                    page.get_by_role("button",name="+ 10 ticks").click()
                page.get_by_label("Order type").select_option("market")
                page.get_by_label("Quantity (shares)").fill("50")
                page.get_by_role("button",name="Submit paper order").click()
                expect(page.get_by_text("Order accepted. 50 of 50 shares filled immediately.")).to_be_visible()
                page.screenshot(path=SHOTS/"marketlab-desktop.png",full_page=True)
                for width, height in [(1440,1060),(390,844)]:
                    page.set_viewport_size({"width":width,"height":height})
                    for route in ["clearledger","marketlab"]:
                        page.goto(base+"/"+route)
                        expect(page.locator("h1")).to_be_visible()
                        overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                        assert not overflow, f"Horizontal viewport overflow: {route} at {width}px"
                        if width==390:
                            page.screenshot(path=SHOTS/f"{route}-mobile.png",full_page=True)
                checks.append("1440px desktop / 390px mobile layout without viewport overflow")
                assert errors == [], errors
                checks.append("zero browser JavaScript exceptions")
                browser.close()
            report={"checks":checks,"passed":len(checks),"browser_errors":errors,"data":"isolated temporary database and session"}
            (ROOT/"artifacts"/"browser-check.json").write_text(json.dumps(report,indent=2)+"\n")
            print(json.dumps(report,indent=2))
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            log.close()


if __name__ == "__main__":
    main()
