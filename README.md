# Mahjong Legend — Game Studio 0.9.1

An original five-reel cascade game with **virtual, non-redeemable credits**. The public game remains at `/`; the separate authenticated configuration workspace is at `/studio/`.

The 0.9 engine provides persistent Django/PostgreSQL storage, immutable releases, ticket-pinned rules, exactly-once round settlement, React/TypeScript Studio, image/audio processing, Math Lab jobs, and backup/restore. UI patch **0.9.1** restores the approved red/gold control panel, ornate result banner, framed counters, and original control graphics while retaining large touch targets. The baseline math snapshot remains **0.8.0** and its evaluator source is unchanged.

## Game and Studio

- One continuous red/gold stage footer: Spin **80–96 px**, Turbo/Auto **52–60 px**, ± **44 px**. The Spin disc remains jade/gold; the panel behind it uses the approved crimson stage treatment. Portrait, landscape and PWA safe areas have explicit geometry; tile faces remain 2:3.
- Draft controls for betting denominations, initial virtual credits, Auto policies, symbol weights, paytable, multipliers, free spins and payout cap.
- All 17 tile symbols × normal/gold states. Verified derivatives are 218×327 RGBA tiles, with whole-tile/glyph, contain/cover and anchor controls.
- Scene slots for background, crown, board and continuous footer.
- Audio waveform, seek/zoom, live spectrum, on-demand spectrogram, original/recipe audition and exact rendered-file playback; trim/fade/gain/pan/filters/three-band EQ; event mapping, buses and base/bonus music loops.
- Workers preserve immutable originals and generate new derivatives. Draft assets remain private until a validated release references them.
- Math Lab reports complete-paid-round RTP estimates, confidence intervals, payout/bonus frequencies and cap observations from independent server-generated seed domains. Changed math requires fresh validation bound to the exact candidate before publication.
- Owner, Editor and Tester permissions, CSRF, revision conflicts, login throttling, upload limits and audit records are enforced server-side.

## Persistent game contract

`GET /api/state` returns a Spin ticket, seed commitment and exact release manifest. `POST /api/spin` requires the offered **string** `bet`, `ticket_id` and UUID `idempotency_key`. Repeating a settled request returns the stored response without a second debit.

The server claims a ticket in a short transaction, computes outside it, and atomically settles balance, ledger, transcript, consumed ticket and next ticket. Leases and fencing prevent stale processes from settling twice. Pending tickets cannot change stake or be reset. Failed calculations do not debit credits.

Publishing changes future tickets. Existing tickets retain both rules and bet policy; all cascades/free spins use their original snapshot. Responses separate `round_manifest` from the next ticket's state. The renderer adopts new manifests after playback. Historical replay uses the recorded release.

Old in-memory `MLSESSION` balances cannot be recovered after their process stops. The first 0.9.0 visit displays a virtual-balance cutover notice. New `MLGAME` sessions persist in PostgreSQL across deployments. No player identity account or payment system is introduced.

## Local development

Requirements: Python 3.12, Node 24, FFmpeg/ffprobe. Install `requirements.txt` and run `npm ci` in `studio_ui/`.

Build from clean repository inputs:

```sh
python tools/build_locked_ui.py
python tools/build_presentation_fx.py
python tools/build_approved_ui.py
python tools/build_portrait_ui.py
python tools/build_responsive_runtime.py --runtime-only
python tools/build_fullframe_ui.py --runtime-only
python tools/build_studio_runtime.py
npm --prefix studio_ui run build
```

Builders generate runtime derivatives. Do not replace frozen, integrity-checked source files with generated outputs in Git. Docker builds them in isolated stages.

For a local SQLite workspace:

```sh
python manage.py migrate
python manage.py bootstrap_studio
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8765
```

Run `python manage.py studio_worker` in another terminal. Sign in at `http://127.0.0.1:8765/studio/`. The legacy `python -m mahjong_legend` server remains a math/presentation regression fixture; it does not implement the persistent Studio contract.

## Railway deployment

| Resource | Responsibility |
|---|---|
| `mahjong-legend-web` | `STUDIO_ROLE=web`: migrations, baseline import, private-storage verification, Gunicorn and `/health` |
| `mahjong-studio-worker` | `STUDIO_ROLE=worker`: durable media/Math Lab jobs, storage verification and heartbeat; no HTTP listener |
| `Postgres` | Persistent versions, tickets, ledger, admin sessions and jobs |
| `mahjong-studio-media` | Private immutable original/derivative object bytes |

Production requires `STUDIO_PRODUCTION=1`, PostgreSQL `DATABASE_URL`, a strong `DJANGO_SECRET_KEY`, explicit `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`, and the `STUDIO_S3_*` connection variables. Railway database/bucket variable references keep credentials out of frontend bundles and Git.

Configure `/health` only on the web service. Shared `railway.json` omits an HTTP healthcheck so the worker can use the same repository. `healthcheck.railway.app` is explicitly allowed. Startup fails closed if durable storage is missing; both roles verify a harmless immutable write/read. Health reports the database backend and recent worker heartbeat.

First-owner activation uses a private high-entropy `STUDIO_SETUP_TOKEN`; the owner chooses their username and password. Activation permanently closes after first use. There are no default credentials or public registration. Additional administrator management uses Django commands and Owner/Editor/Tester groups.

## Verification

The workflow retains original deterministic math, artwork, motion, reel continuity and PWA regressions. A separate PostgreSQL job tests real row-lock concurrency, stale-worker recovery, release deduplication, idempotency, permissions, conflicts, media transforms and backup/restore. Chromium and WebKit exercise Django and the complete Studio edit → render → preview → validate → publish → rollback flow.

```sh
python manage.py test game_studio
python -m unittest discover -s tests -p test_studio_media.py
python tools/qa_studio_engine_v090.py
python tools/qa_studio_engine_v090.py --engine webkit
python studio_ui/qa_studio.py --engine chromium
python studio_ui/qa_studio.py --engine webkit
```

The main-branch live gate compares exact deployed files, checks protected Studio endpoints/storage/worker health, and verifies one HTTPS virtual Spin and replay. Release completion also requires Railway terminal `SUCCESS`.

## Operations and limits

See [0.9.1 visual correction](docs/RELEASE_V091.md), [0.9.0 engine release](docs/RELEASE_V090.md), [media/audio contracts](docs/STUDIO_MEDIA.md), [backup/restore](docs/STUDIO_BACKUP.md), [Studio UI guide](studio_ui/README.md), and [baseline math evidence](docs/MATH_V080_VALIDATION.md).

Backups include database records and actual uploaded bytes. They contain private authentication/session material and unrevealed ticket seeds, are created with 0600 permissions, and have no HTTP download endpoint. Restore requires an empty migrated destination, with no destructive force option. Scheduling and offsite retention are not automatically enabled.

All credits remain virtual: no purchases, deposits, transfers, redemption or real-money gambling. Deterministic replay is not RNG certification. Automated browsers and simulated insets do not establish physical-iPhone PWA behavior, speaker loudness or listening quality. The baseline 1.30 signal gain preserves saved preferences and mute; no true-peak limiter guarantee is made.
