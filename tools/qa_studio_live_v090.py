"""Verify built UI 0.9.0 bytes and one real public virtual-credit round.

This gate never activates an owner, signs in, uploads, edits a draft, publishes,
or changes infrastructure. Deployment polling is GET-only and bounded to eight
minutes. Once a Spin is attempted it is never automatically retried here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import argparse
import json
import os
from pathlib import Path
import posixpath
import re
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import Error as BrowserError, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from qa_fullframe_v086 import (assert_background_images, assert_control_hits,
                               assert_layout, install_viewport_fixture, set_safe_area)

PRODUCTION_URL = "https://mahjong-legend-web-production.up.railway.app"
VERSION = "0.9.0"
ENGINE_HASH = sha256((ROOT / "mahjong_legend/engine.py").read_bytes()).hexdigest()


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


class HTMLAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        value = attributes.get("src") if tag in {"script", "img"} else attributes.get("href") if tag == "link" else None
        if value:
            self.paths.append(value)


def expected_files(web_root):
    required = {
        "index.html", "sw.js", "manifest.webmanifest", "studio/index.html",
        "assets/studio-v090/game.js", "assets/studio-v090/audio.js", "assets/studio-v090/release.json",
        "assets/fullframe-v086/layout.css", "assets/fullframe-v086/layout.js", "assets/portrait-v085/reels.js",
    }
    web_root = web_root.resolve()
    for html in ("index.html", "studio/index.html"):
        require((web_root / html).is_file(), "Build the game and Studio before live verification")
        parser = HTMLAssets()
        parser.feed((web_root / html).read_text())
        for ref in parser.paths:
            parsed = urlsplit(ref)
            if parsed.scheme or parsed.netloc or ref.startswith("data:"):
                continue
            path = parsed.path.lstrip("/") if ref.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(html), parsed.path))
            required.add(path)
    # Every compiled Studio bundle, including lazy chunks, belongs to the gate.
    required.update(str(path.relative_to(web_root)) for path in (web_root / "studio").rglob("*") if path.is_file())
    # Include the actual presentation artwork referenced by compiled styles.
    for css in [path for path in required if path.endswith(".css")]:
        require((web_root / css).is_file(), "A referenced compiled stylesheet is missing")
        for match in re.finditer(r'''url\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^)]*))\s*\)''', (web_root / css).read_text()):
            ref = next(group for group in match.groups() if group is not None).strip()
            parsed = urlsplit(ref)
            if parsed.scheme or parsed.netloc or not parsed.path or ref.startswith("data:"):
                continue
            path = parsed.path.lstrip("/") if ref.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(css), parsed.path))
            required.add(path)
    required.update(str(path.relative_to(web_root)) for path in (web_root / "assets/portrait-v085/tiles").glob("*.webp"))
    result = {}
    for relative in sorted(required):
        path = (web_root / relative).resolve()
        require(path.is_relative_to(web_root) and path.is_file(), f"Built release file is missing: {relative}")
        data = path.read_bytes()
        result[relative] = {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
    release = json.loads((web_root / "assets/studio-v090/release.json").read_text())
    require(release.get("release") == VERSION and release.get("studio") is True, "Expected build is not Studio 0.9.0")
    require('data-release="0.9.0"' in (web_root / "index.html").read_text(), "Expected HTML is not UI 0.9.0")
    return result


class HTTPReader:
    def __init__(self, base, allow_proxy_bypass, receipt):
        self.base = base
        self.allow_proxy_bypass = allow_proxy_bypass
        self.receipt = receipt
        self.context = ssl.create_default_context()

    def get(self, path, deadline, maximum=1024 * 1024):
        require(time.monotonic() < deadline, "Deployment verification deadline reached")
        request = Request(self.base + path, headers={"Cache-Control": "no-cache", "User-Agent": "Mahjong-Release-QA/0.9.0"})
        try:
            response = urlopen(request, timeout=max(.2, min(8, deadline-time.monotonic())), context=self.context)
        except URLError as error:
            if (self.allow_proxy_bypass and isinstance(error.reason, ssl.SSLCertVerificationError)
                    and not self.receipt["urllib_proxy_tls_bypass"]):
                self.context = ssl._create_unverified_context()
                self.receipt["urllib_proxy_tls_bypass"] = True
                self.receipt["urllib_bypass_reason"] = "Observed certificate verification failure in the explicitly permitted proxy environment"
                return self.get(path, deadline, maximum)
            raise
        with response:
            require(urlsplit(response.url).netloc == urlsplit(self.base).netloc, "Unexpected cross-origin redirect")
            chunks, size = [], 0
            read = getattr(response, "read1", response.read)
            while True:
                require(time.monotonic() < deadline, "Deployment verification deadline reached")
                chunk = read(min(128*1024, maximum-size+1))
                if not chunk:
                    break
                size += len(chunk)
                require(size <= maximum, "HTTP response exceeded its expected size")
                chunks.append(chunk)
            return b"".join(chunks)

    def json(self, path, deadline):
        return json.loads(self.get(path, deadline))


def wait_for_exact_release(reader, expected, expected_storage, require_worker, wait_seconds):
    started = time.monotonic()
    deadline = started + wait_seconds
    last_error = "Not checked"
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        try:
            health = reader.json("/health", deadline)
            require(health.get("ok") is True and health.get("version") == VERSION, "Previous web release is still serving")
            require(health.get("storage") == expected_storage, "Persistent database health is not ready")
            require(health.get("engine_sha256") == ENGINE_HASH, "Deployed engine hash differs from this build")
            if require_worker:
                require(health.get("worker_ready") is True, "Worker heartbeat is not ready")

            def fetch_file(item):
                path, local = item
                body = reader.get("/" + quote(path, safe="/") + "?qa090=" + local["sha256"][:16], deadline, local["bytes"] + 1)
                return path, {"sha256":sha256(body).hexdigest(), "bytes":len(body)}

            with ThreadPoolExecutor(max_workers=6) as pool:
                actual = dict(pool.map(fetch_file, expected.items()))
            mismatches = [name for name in expected if actual.get(name) != expected[name]]
            require(not mismatches, "Previous/mixed files still serving: " + ", ".join(mismatches[:4]))
            return {"health":health, "files":actual, "attempts":attempts,
                    "elapsed_seconds":round(time.monotonic()-started, 3), "exact_files":"PASS"}
        except (VerificationError, OSError, ValueError, HTTPError, URLError) as error:
            last_error = str(error)[:400]
            if time.monotonic() >= deadline:
                break
            print(f"Waiting for exact UI {VERSION}, attempt {attempts}: {last_error}", flush=True)
            time.sleep(min(5, max(0, deadline-time.monotonic())))
    raise VerificationError("Exact deployment was not verified within the polling deadline: " + last_error)


def ready_game(page):
    expect(page.locator("#game-stage")).to_have_attribute("data-release", VERSION)
    expect(page.locator("#soft-tech-continue")).to_be_enabled(timeout=30000)
    page.locator("#soft-tech-continue").click()
    expect(page.locator("#soft-tech-splash")).to_be_hidden()
    page.wait_for_function("window.MahjongStudioRuntime?.manifest && document.querySelector('#stage-notice').textContent !== 'MEMUAT GAME'", timeout=30000)
    page.locator("#board").evaluate("element => Promise.all([...element.querySelectorAll('img')].map(image => image.decode()))")
    require(page.locator("#board .tile").count() == 23, "Expected 23 visible game tiles")


def verify_browser(base, output, tls, allow_proxy_bypass, browser_path=None):
    report = {"engine":"chromium", "page_errors":[], "spin_requests":0,
              "physical_device_tested":False, "standalone_installation_tested":False}
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, **({"executable_path":browser_path} if browser_path else {}))
        context = browser.new_context(viewport={"width":390,"height":690}, device_scale_factor=2, is_mobile=True, has_touch=True)
        page = context.new_page()
        try:
            page.goto(base, wait_until="networkidle", timeout=45000)
        except BrowserError as error:
            if allow_proxy_bypass and ("ERR_CERT" in str(error) or "certificate" in str(error).lower()):
                context.close()
                tls["browser_proxy_tls_bypass"] = True
                tls["browser_bypass_reason"] = "Observed browser certificate error in the explicitly permitted proxy environment"
                context = browser.new_context(viewport={"width":390,"height":690}, device_scale_factor=2,
                                              is_mobile=True, has_touch=True, ignore_https_errors=True)
                page = context.new_page()
                page.goto(base, wait_until="networkidle", timeout=45000)
            else:
                raise
        # Attach before reloading the document to include all startup errors.
        page.on("pageerror", lambda error:report["page_errors"].append(str(error)))
        requests = []
        context.on("request", lambda request: requests.append(request)
                   if urlsplit(request.url).path == "/api/spin" and request.method == "POST" else None)
        page.reload(wait_until="networkidle")
        ready_game(page)
        before_response = context.request.get(base + "/api/state")
        require(before_response.status == 200, "Public state did not load")
        before = before_response.json()
        require(before.get("ui_version") == VERSION and before.get("session_storage") == "persistent", "Game session is not using the new durable engine")
        require(before.get("virtual_credits_only") is True and not before.get("preview"), "Expected a public virtual-credit session")
        require("secret_seed" not in json.dumps(before), "Public state leaked a future seed field")
        commitment = before["next_seed_commitment_sha256"]
        expect(page.locator("#next-commit")).to_have_text(commitment)
        geometry = assert_layout(page, 390, 690)
        assert_control_hits(page)
        decoded = assert_background_images(page)

        # Exactly one real click. Errors after this point fail the gate instead of
        # retrying a paid request or issuing a second synthetic API Spin.
        with page.expect_response(lambda response:urlsplit(response.url).path == "/api/spin" and response.request.method == "POST", timeout=130000) as pending:
            page.locator("#spin-btn").click()
        response = pending.value
        require(response.status == 200, "The single public Spin was not accepted")
        result = response.json()
        submitted = response.request.post_data_json
        require(submitted.get("ticket_id") == before["ticket"]["id"], "UI Spin did not use its committed ticket")
        require(result.get("ticket_id") == before["ticket"]["id"], "Server settled a different ticket")
        require(submitted.get("idempotency_key") == result.get("idempotency_key"), "Idempotency key changed in settlement")
        record = result["round"]
        require(sha256(bytes.fromhex(record["seed_hex"])).hexdigest() == commitment == record["seed_commitment_sha256"], "Seed reveal does not match the pre-Spin commitment")
        require(record["config_sha256"] == before["config_sha256"], "Math snapshot changed inside the committed round")
        require(result["round_release_id"] == before["ticket"]["release_id"], "Release pin changed inside the committed round")
        expect(page.locator("#spin-count")).to_have_text(str(before["spin_count"]+1), timeout=180000)
        expect(page.locator("#spin-btn")).to_have_attribute("aria-label", "Spin", timeout=180000)
        expect(page.locator("#game-stage")).to_have_attribute("data-motion-phase", "idle")
        require(len(requests) == 1, "One UI click emitted more than one Spin POST")
        after = context.request.get(base + "/api/state").json()
        require(after["spin_count"] == before["spin_count"]+1, "Session accepted an unexpected number of rounds")
        require(after["ticket"]["id"] != before["ticket"]["id"] and after["ticket"]["sequence"] == before["ticket"]["sequence"]+1,
                "Settlement did not issue the next ticket exactly once")
        require(after["balance"] == result["state"]["balance"], "Persisted balance differs from settlement response")
        expected_balance = Decimal(before["balance"]) - Decimal(result["stake_virtual_credits"]) + Decimal(result["win_virtual_credits"])
        require(abs(Decimal(after["balance"])-expected_balance) < Decimal(".000002"), "Virtual-credit settlement does not reconcile")
        motion = page.evaluate("MahjongReels.diagnostics()")
        require(motion and motion.get("completed") is True and not motion.get("cancelled") and not motion.get("errors")
                and motion.get("stops") == [1,2,3,4,5], "Reel presentation did not complete in order")
        actual_board = page.locator("#board").evaluate("element => [...element.children].map(column => [...column.children].filter(tile => tile._tile).map(tile => tile._tile))")
        expected_board = [event["board"] for event in record["events"] if event["type"] == "screen_end"][-1]
        require(actual_board == expected_board, "Visible final board differs from the committed engine result")
        page.locator("#menu-btn").click()
        page.locator('[data-panel="fairness"]').click()
        with page.expect_response(lambda response:urlsplit(response.url).path == "/api/verify", timeout=30000) as verification:
            page.locator("#verify-btn").click()
        replay = verification.value.json()
        require(verification.value.status == 200 and replay.get("valid") is True, "Historical replay did not pass")
        expect(page.locator("#verification-result")).to_have_text(re.compile(r"^PASS"))
        page.locator("#close-dialog").click()
        page.screenshot(path=str(output / "chromium-live-390x690.png"))
        audio = page.evaluate("MahjongWildAudio.state")
        require(audio.get("unlocked") is True and audio.get("context") == "running", "Game audio did not unlock from the real user gesture")
        require(abs(float(audio["outputGain"])-float(after["manifest"]["audio"]["output_gain"])) < 1e-8,
                "Runtime audio output gain differs from the adopted release")
        require(not audio.get("lastError"), "A runtime audio asset failed to load or decode")
        worker = page.evaluate("""async()=>{
          if(!('serviceWorker' in navigator)) return {available:false,controlled:false,ready:false};
          const registration=await Promise.race([navigator.serviceWorker.ready,new Promise(resolve=>setTimeout(()=>resolve(null),6000))]);
          return {available:true,controlled:!!navigator.serviceWorker.controller,ready:!!registration};
        }""")
        if not tls["browser_proxy_tls_bypass"]:
            require(worker["ready"], "Service worker did not become ready")

        # Anonymous Studio navigation only; never enter or submit owner credentials.
        anonymous = context.request.get(base + "/api/studio/session")
        require(anonymous.status == 200, "Studio session endpoint unavailable")
        identity = anonymous.json()
        require(identity.get("authenticated") is False and identity.get("user") is None, "Studio is unexpectedly authenticated")
        require(context.request.get(base + "/api/studio/assets").status == 401, "Private asset library is readable anonymously")
        studio = context.new_page()
        studio.on("pageerror", lambda error:report["page_errors"].append(str(error)))
        studio.set_viewport_size({"width":1440,"height":1000})
        studio.goto(base + "/studio/", wait_until="networkidle")
        expect(studio.locator("form.login-form")).to_be_visible(timeout=30000)
        expect(studio.locator('input[autocomplete="username"]')).to_be_visible()
        require(not studio.locator(".studio .sidebar").count(), "Private Studio workspace rendered for an anonymous user")
        studio.screenshot(path=str(output / "chromium-live-studio-anonymous.png"))
        report["studio"] = {"anonymous":True,"asset_library_status":401,
                            "setup_required":bool(identity.get("setup_required")),"version":identity.get("version"),
                            "owner_created":False,"authenticated_mutations":0}
        studio.close()

        pwa_context = browser.new_context(viewport={"width":390,"height":844}, device_scale_factor=2,
            is_mobile=True, has_touch=True, ignore_https_errors=tls["browser_proxy_tls_bypass"])
        pwa_context.on("request", lambda request: requests.append(request)
                       if urlsplit(request.url).path == "/api/spin" and request.method == "POST" else None)
        pwa = pwa_context.new_page()
        pwa.on("pageerror", lambda error:report["page_errors"].append(str(error)))
        install_viewport_fixture(pwa, standalone=True, visual_height=751)
        pwa.goto(base, wait_until="networkidle")
        ready_game(pwa)
        set_safe_area(pwa, 59, 34)
        pwa_geometry = assert_layout(pwa, 390, 844, 59, 34)
        assert_control_hits(pwa)
        assert_background_images(pwa)
        pwa.screenshot(path=str(output / "chromium-live-simulated-pwa-390x844.png"))
        require(not report["page_errors"], "Browser JavaScript errors occurred")
        require(len(requests) == 1, "Unexpected additional Spin request during read-only checks")
        report.update({"result":"PASS", "spin_requests":len(requests), "accepted_rounds":1,
                       "seed_commitment":"PASS", "ticket_pinning":"PASS", "next_ticket":"PASS",
                       "round_id":record["round_id"], "replay":"PASS", "final_board":"MATCH",
                       "persistent_balance":"PASS", "reel_motion":motion, "audio":audio,
                       "mobile":{"viewport":[390,690],"stage":geometry["stage"],"controls":geometry["controls"],"decoded_backgrounds":len(decoded)},
                       "simulated_pwa":{"layout":[390,844],"visual":[390,751],"safe_area":{"top":59,"bottom":34},
                                        "stage":pwa_geometry["stage"],"controls":pwa_geometry["controls"],"physical_device":False},
                       "service_worker":worker})
        pwa_context.close()
        context.close()
        browser.close()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("MW_LIVE_URL", PRODUCTION_URL))
    parser.add_argument("--web-root", type=Path, default=ROOT / "web")
    parser.add_argument("--output", type=Path, default=ROOT / "qa/studio-live-v090")
    parser.add_argument("--wait-seconds", type=float, default=480)
    parser.add_argument("--allow-local", action="store_true")
    parser.add_argument("--expected-storage", choices=["postgresql","sqlite-local"], default="postgresql")
    parser.add_argument("--allow-proxy-tls-bypass", action="store_true",
                        default=os.environ.get("MW_QA_ALLOW_PROXY_TLS_BYPASS") == "1")
    parser.add_argument("--browser")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    parsed = urlsplit(base)
    local = args.allow_local and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1","localhost"}
    require(not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment,
            "Use a bare authorized origin without credentials or paths")
    require(base == PRODUCTION_URL or local, "Unexpected deployment target")
    require(local or args.expected_storage == "postgresql", "Production gate requires PostgreSQL")
    require(0 < args.wait_seconds <= 480, "Polling deadline must be between zero and eight minutes")
    args.output.mkdir(parents=True, exist_ok=True)
    tls = {"proxy_bypass_explicitly_allowed":args.allow_proxy_tls_bypass,
           "urllib_proxy_tls_bypass":False,"browser_proxy_tls_bypass":False}
    report = {"result":"RUNNING","url":base,"scope":"local-rehearsal" if local else "public-production",
              "ui_release":VERSION,"expected_engine_sha256":ENGINE_HASH,"tls":tls,
              "railway_terminal_status":"Not checked by this script; requires an independent deployment receipt"}
    stage = "build-inventory"
    try:
        expected = expected_files(args.web_root)
        stage = "deployment-hashes"
        reader = HTTPReader(base, args.allow_proxy_tls_bypass, tls)
        report["deployment"] = wait_for_exact_release(reader, expected, args.expected_storage, not local, args.wait_seconds)
        stage = "browser-round-and-anonymous-studio"
        report["browser"] = verify_browser(base, args.output, tls, args.allow_proxy_tls_bypass, args.browser)
        stage = "final-health"
        final_health = reader.json("/health", time.monotonic()+15)
        require(final_health.get("ok") is True and final_health.get("version") == VERSION
                and final_health.get("engine_sha256") == ENGINE_HASH and final_health.get("storage") == args.expected_storage,
                "Web health changed during verification")
        require(local or final_health.get("worker_ready") is True, "Worker heartbeat stopped during verification")
        report["deployment"]["final_health"] = final_health
        report["result"] = "PASS"
        report["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    except Exception as error:
        report.update(result="FAIL", failed_stage=stage, error=str(error)[:1200])
        raise
    finally:
        (args.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result":"PASS","scope":report["scope"],"url":base,"ui_release":VERSION,
                      "file_hashes":len(expected),"spin_posts":1,"replay":"PASS","tls":tls,
                      "receipt":str(args.output / "receipt.json")}))


if __name__ == "__main__":
    main()
