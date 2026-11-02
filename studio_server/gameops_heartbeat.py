"""Read-only game health transport. Never exports browser events or touches balances."""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request

RECEIVER = "https://playground-admin-production.up.railway.app/api/v2/game-bridge"
LOG = logging.getLogger("gameops-bridge")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def signed_headers(key_id, secret, payload, timestamp=None, nonce=None):
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    nonce = secrets.token_hex(16) if nonce is None else nonce
    message = "\n".join(["gameops.v2", "POST", "/api/v2/game-bridge", timestamp, nonce,
                         hashlib.sha256(payload).hexdigest()]).encode("ascii")
    mac = hmac.new(bytes.fromhex(secret), message, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-GameOps-Key": key_id,
            "X-GameOps-Timestamp": timestamp, "X-GameOps-Nonce": nonce,
            "X-GameOps-Signature": mac}


def verify_receipt(secret, nonce, payload, signature):
    if not re.fullmatch(r"[a-f0-9]{64}", signature or ""):
        return False
    message = "\n".join(["gameops.receipt.v2", nonce, hashlib.sha256(payload).hexdigest()]).encode("ascii")
    expected = hmac.new(bytes.fromhex(secret), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def start_bridge(game, version="unknown"):
    if os.environ.get("GAMEOPS_BRIDGE_ENABLED") != "1":
        return lambda: None
    key = os.environ.get("GAMEOPS_BRIDGE_KEY_ID", "")
    secret = os.environ.get("GAMEOPS_BRIDGE_SECRET", "")
    environment = os.environ.get("GAMEOPS_ENVIRONMENT", "")
    port = os.environ.get("PORT", "8080")
    if (not re.fullmatch(r"[a-z0-9-]{3,60}", key)
            or not re.fullmatch(r"[a-f0-9]{64}", secret)
            or environment not in ("production", "staging")
            or game not in ("skygate-5000", "uno-luck", "mahjong-wild")
            or not port.isdigit() or not 1 <= int(port) <= 65535
            or os.environ.get("GAMEOPS_RECEIVER_URL", RECEIVER) != RECEIVER):
        LOG.error("[gameops-bridge] invalid_configuration; heartbeat disabled")
        return lambda: None
    stop = threading.Event()
    # Avoid inherited proxy configuration when probing localhost or sending secrets.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    host = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        host = "localhost"

    def tick():
        health, build = "degraded", version
        try:
            req = urllib.request.Request("http://127.0.0.1:" + port + "/health", headers={"Host": host})
            with opener.open(req, timeout=3.5) as response:
                body = response.read(4097)
                if len(body) <= 4096:
                    data = json.loads(body)
                    if data.get("ok") is True:
                        health = "degraded" if data.get("worker_ready") is False else "ok"
                    if isinstance(data.get("version"), str):
                        build = data["version"]
        except (OSError, ValueError, urllib.error.HTTPError):
            pass
        payload = json.dumps({"schema_version": 2, "game": game, "environment": environment,
            "type": "heartbeat", "version": re.sub(r"[^A-Za-z0-9_.:-]", "_", str(build))[:80] or "unknown",
            "health": health, "deployment": os.environ.get("RAILWAY_DEPLOYMENT_ID", "unknown")[:100],
            "capabilities": ["heartbeat"]}, separators=(",", ":")).encode("utf8")
        headers = signed_headers(key, secret, payload)
        request = urllib.request.Request(RECEIVER, data=payload, headers=headers, method="POST")
        try:
            with opener.open(request, timeout=5) as response:
                receipt = response.read(4097)
                if len(receipt) > 4096 or not verify_receipt(secret, headers["X-GameOps-Nonce"], receipt,
                                                           response.headers.get("X-GameOps-Receipt")):
                    raise ValueError("receipt_rejected")
                data = json.loads(receipt)
                if data.get("accepted") is not True or data.get("type") != "heartbeat" or data.get("game") != game:
                    raise ValueError("invalid_receipt")
            # Explicit line retained by Railway without logging response bodies or keys.
            print("[gameops-bridge] heartbeat_acknowledged game=" + game + " environment=" + environment + " local_health=" + health, flush=True)
        except (OSError, ValueError, urllib.error.HTTPError):
            LOG.warning("[gameops-bridge] heartbeat_not_acknowledged game=%s; retry next interval", game)

    def run():
        if stop.wait(3):
            return
        while not stop.is_set():
            try:
                tick()
            except Exception:
                LOG.warning("[gameops-bridge] unexpected transport failure; gameplay unaffected")
            if stop.wait(60):
                return

    threading.Thread(target=run, name="gameops-heartbeat", daemon=True).start()
    return stop.set
