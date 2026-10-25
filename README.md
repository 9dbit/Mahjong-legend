# Mahjong Legend — UI 0.8.6 / math 0.8.0

Mahjong Legend is an **original game prototype** with virtual, non-redeemable credits. The page launches directly into a five-reel Mahjong-style cascade game with 2,000 ways, Wild transformations, multipliers, Free Spins, Auto Spin, and Turbo. It contains no marketing page.

## Online / Railway

This repository connects to Railway and deploys via `Dockerfile` plus `railway.json`. Railway assigns a `PORT`; the server binds to `0.0.0.0` when started with `--public`, serves the game at `/`, and exposes `/health` for platform health checks. `GET /api/state` and `POST /api/spin` are the main game endpoints. Once a Railway domain is generated, the root URL is the playable game URL.

## Start locally from macOS

With Python 3.10+, open Terminal in the repository directory:

```sh
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

The tests cover deterministic math/replay, payout caps, REST endpoints, virtual-stake scaling, browser session isolation, origin checks, artwork identity, and full-frame layout contracts. The release workflow first compiles the approved artwork and runtime derivatives, then runs the unit and Chromium/WebKit suites. See [the UI 0.8.6 build and verification notes](docs/RELEASE_V086.md) for the build sequence. Browser tests use Playwright 1.57.0; artwork builds use Pillow >=10,<13.

## Gameplay and fairness

The current math configuration is **0.8.0**, with base multipliers **1 → 2 → 3 → 5**, bonus multipliers **2 → 3 → 5 → 8**, and a **1000× total payout cap per paid round**, including its free spins. The earlier v0.1–v0.3 RTP estimates do not validate this configuration. Current reproducible Monte Carlo results, seed domains, source hashes, and uncertainty are documented in [the math 0.8.0 validation report](docs/MATH_V080_VALIDATION.md). Simulation estimates are not certified or exact theoretical RTP.

UI 0.8.6 fits the portrait browser viewport while retaining the approved artwork, 23 live tiles with 2:3 faces, circular Spin controls, and safe-area handling. Browser automation and simulated insets do not establish physical-iPhone performance, PWA installation, or audible sound quality.

### Public demo boundaries

- Virtual credits only, no deposits, withdrawals, purchases, monetary awards, identity accounts, or real-money play.
- Each browser gets an opaque HttpOnly + Secure cookie-backed session (`MLSESSION`) with its own balance, seed commitment, and round history. The server stores sessions in memory with a 24-hour idle expiry and bounded capacity.
- A Railway restart or redeploy resets all player balances. No user data or wallet database is required. One service replica is recommended for session consistency.
- POST requests use a same-origin check plus a custom request header; HTTPS is required on Railway. CSP and response security headers are applied.
- The prototype has not been independently audited, penetration tested, or certified for gambling use.

The game is inspired by general mechanics found in cascading Mahjong-style games, but uses original code and drawings. PG Soft source assets and trademarks are not included.
