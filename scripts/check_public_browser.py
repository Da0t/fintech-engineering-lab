"""Verify anonymous access, working engines, and isolated visitor sessions."""
import argparse
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

ROOT=Path(__file__).resolve().parents[1]


def check(base):
    checks=[]
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch()
        first=browser.new_context(viewport={"width":1440,"height":1060})
        second=browser.new_context(viewport={"width":390,"height":844})
        a,b=first.new_page(),second.new_page()
        for page in (a,b):
            page.on("pageerror", lambda error: errors.append(str(error)))
            response=page.goto(base+"/clearledger")
            assert response.status==200
            expect(page.get_by_role("heading",name="Every dollar. Accounted for.")).to_be_visible(timeout=30000)
            expect(page.get_by_text("$2,900.00",exact=True)).to_be_visible()
        checks.append("anonymous desktop and mobile access without login")
        a.get_by_role("button",name="Simulate deposit").click()
        a.get_by_label("Amount (USD)").fill("100.00")
        a.get_by_role("button",name="Process deposit").click()
        expect(a.get_by_text("$3,000.00",exact=True)).to_be_visible(timeout=30000)
        b.reload()
        expect(b.get_by_text("$2,900.00",exact=True)).to_be_visible()
        a.reload()
        expect(a.get_by_text("$3,000.00",exact=True)).to_be_visible()
        checks.append("ledger visitor isolation and same-tab refresh persistence")
        a.get_by_role("button",name="Run failure scenario").click()
        expect(a.get_by_role("button",name="Retry event")).to_be_visible(timeout=30000)
        a.get_by_role("button",name="Retry event").click()
        expect(a.get_by_text("$3,129.00",exact=True)).to_be_visible(timeout=30000)
        checks.append("public ledger incident and recovery")
        for page in (a,b):
            page.get_by_role("link",name="MarketLab — execution and replay").click()
            expect(page.get_by_role("heading",name="The price is only the beginning.")).to_be_visible(timeout=30000)
        a.get_by_role("button",name="Submit paper order").click()
        expect(a.get_by_text("Order accepted. 50 of 50 shares filled immediately.")).to_be_visible(timeout=30000)
        expect(a.locator('.stats .stat').nth(2)).to_contain_text('150')
        expect(b.locator('.stats .stat').nth(2)).to_contain_text('100')
        a.get_by_role("button",name="+ 10 ticks").click()
        a.get_by_role("button",name="Verify replay").click()
        expect(a.locator('#toast')).to_contain_text('Replay verified',timeout=30000)
        a.reload()
        expect(a.locator('.stats .stat').nth(2)).to_contain_text('150',timeout=30000)
        checks.append("real Java fills, visitor isolation, and deterministic replay")
        a.get_by_role("button",name="Thin",exact=True).click()
        a.get_by_role("button",name="Submit paper order").click()
        expect(a.get_by_text("Order accepted. 45 of 50 shares filled immediately.")).to_be_visible(timeout=30000)
        checks.append("public thin-liquidity partial fills")
        a.get_by_role("button",name="New session").click()
        expect(a.locator('.stats .stat').nth(2)).to_contain_text('100',timeout=30000)
        a.get_by_role("link",name="ClearLedger — money movement").click()
        expect(a.get_by_text("$3,129.00",exact=True)).to_be_visible(timeout=30000)
        a.get_by_role("button",name="New session").click()
        expect(a.get_by_text("$2,900.00",exact=True)).to_be_visible(timeout=30000)
        checks.append("reset affects only selected project in selected visitor session")
        for page in (a,b):
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not errors, errors
        checks.append("responsive layout and no JavaScript exceptions")
        browser.close()
    report={"url":base,"checks":checks,"passed":len(checks),"browser_errors":errors,"authentication":"none; two fresh browser contexts"}
    (ROOT/'artifacts'/'public-browser-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url')
    args=parser.parse_args()
    if args.url:
        check(args.url.rstrip('/'))
        return
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        with open(Path(directory)/'server.log','w+') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,
                env={**os.environ,'PUBLIC_DEMO':'1'},stdout=log,stderr=log)
            base=f'http://127.0.0.1:{port}'
            try:
                for _ in range(100):
                    try:
                        with urlopen(base+'/health',timeout=1):
                            break
                    except Exception:
                        time.sleep(.1)
                check(base)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__=='__main__':
    main()
