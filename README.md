# Mahjong Legend — UI v0.8.2 / math v0.8.0

Mahjong Legend is an **original game prototype** with virtual, non-redeemable credits. The page launches directly into a five-reel Mahjong-style cascade game with 2,000 ways, Wild transformations, multipliers, Free Spins, Auto Spin, and Turbo. It contains no marketing page.

## Online / Railway

This repository connects to Railway and deploys via `Dockerfile` plus `railway.json`. Railway assigns a `PORT`; the server binds to `0.0.0.0` when started with `--public`, serves the game at `/`, and exposes `/health` for platform health checks. `GET /api/state` and `POST /api/spin` are the main game endpoints. Once a Railway domain is generated, the root URL is the playable game URL.

## Start locally from macOS

With Python 3.10+, open Terminal in the repository directory:

```sh
python3 -m pip install 'Pillow>=10,<13'
python3 tools/build_locked_ui.py
python3 tools/build_presentation_fx.py
python3 tools/build_pwa.py
python3 tools/build_oriental_audio.py
python3 -m mahjong_legend
```

Then open http://127.0.0.1:8765 on the Mac. Local mode listens only on the loopback interface. Production mode is explicit:

```sh
python3 -m mahjong_legend --public
```

## Automated tests

```sh
python3 -m unittest discover -s tests -q
```

Unit tests cover deterministic math/replay, payout cap, REST endpoints, HTTP controls, virtual-stake scaling, browser session isolation, origin checks, and health endpoint. The CI workflow also checks the actual interface and motion in Chromium and WebKit, plus the public HTTPS release after main is deployed.

## Gameplay and fairness

The engine uses base multipliers **×1 → ×2 → ×3 → ×5** and bonus multipliers **×2 → ×3 → ×5 → ×8**. UI v0.8.2 changes presentation, audio, menus, and the PWA display only. Engine and configuration bytes are unchanged from math v0.8.0.

**RTP has not been revalidated after the base multiplier changed to ×5.** Earlier simulation figures belong to earlier configurations and must not be presented as the RTP of this release. Outcomes remain replayable through the deterministic engine.

### Public demo boundaries

- Virtual credits only, no deposits, withdrawals, purchases, monetary awards, identity accounts, or real-money play.
- Each browser gets an opaque HttpOnly + Secure cookie-backed session (`MLSESSION`) with its own balance, seed commitment, and round history. The server stores sessions in memory with a 24-hour idle expiry and bounded capacity.
- A Railway restart or redeploy resets all player balances. No user data or wallet database is required. One service replica is recommended for session consistency.
- POST requests use a same-origin check plus a custom request header; HTTPS is required on Railway. CSP and response security headers are applied.
- The prototype has not been independently audited, penetration tested, or certified for gambling use.

The game is inspired by general mechanics found in cascading Mahjong-style games, but uses original code and drawings. PG Soft source assets and trademarks are not included.

