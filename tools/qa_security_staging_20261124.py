"""Bounded, non-destructive black-box acceptance against isolated staging only.

DO NOT point this at live sites. No wallet credentials, owner login, rate tests,
fuzzing, real transactions, or durable environment changes are performed.
"""
import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ORIGIN="https://mahjong-staging-web-staging.up.railway.app"

def request(path, *, method="GET", payload=None, headers=None):
    url=ORIGIN+path
    parsed=urlsplit(url)
    assert parsed.scheme=="https" and parsed.hostname=="mahjong-staging-web-staging.up.railway.app"
    data=None if payload is None else json.dumps(payload).encode()
    r=urllib.request.Request(url,data=data,headers=headers or {},method=method)
    try:
        response=urllib.request.urlopen(r,timeout=12,context=ssl.create_default_context())
    except urllib.error.HTTPError as exc:
        response=exc
    with response:
        raw=response.read(1024*1024+1)
        assert len(raw)<=1024*1024, "Overlarge staging HTTP response"
        return response.status,dict(response.headers.items()),raw

def check():
    status,headers,raw=request("/health")
    assert status==200, ("health",status,raw[:200])
    health=json.loads(raw)
    assert health.get("ok") and health.get("game")=="Mahjong Wild"
    assert health.get("storage")=="postgresql"
    assert health.get("worker_ready") is True
    status,headers,raw=request("/api/studio/session")
    assert status==200
    session=json.loads(raw)
    assert session.get("authenticated") is False and session.get("user") is None
    for name in ("content-security-policy","x-content-type-options","x-frame-options"):
        assert any(k.lower()==name for k in headers), "Missing "+name
    assert not any(k.lower()=="access-control-allow-origin" and v=="*" for k,v in headers.items())
    status,headers,raw=request("/api/studio/assets")
    assert status==401, ("unauthorized studio assets",status,raw[:200])
    status,headers,raw=request("/.env")
    assert status==404, ("secret file path refused",status)
    status,headers,raw=request("/api/spin",method="POST",payload={"bet":"1"},headers={
        "Content-Type":"application/json",
        "Origin":"https://untrusted.example",
        "X-ML-Request":"local-demo",
        "Sec-Fetch-Site":"cross-site"})
    assert status==403, ("cross-origin spin refused",status,raw[:200])
    status,headers,raw=request("/api/studio/drafts",method="POST",payload={},headers={"Content-Type":"application/json"})
    assert status in (401,403), ("unauthenticated studio write refused",status,raw[:200])
    print(json.dumps({
        "result":"PASS",
        "scope":"isolated-staging-only",
        "tests":["postgres-and-worker-ready","anonymous-studio-session","security-headers",
                 "unauthorized-assets-refused","dot-env-not-served",
                 "cross-origin-spin-refused","unauthorized-studio-write-refused"],
        "state_mutations":0,"wallet_calls":0,"gameplay_spins":0
    },sort_keys=True))

if __name__=="__main__":
    check()
