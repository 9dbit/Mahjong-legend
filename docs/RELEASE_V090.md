# Mahjong Legend 0.9.0 — durable game engine and Game Studio

This release adds a separate configuration workspace at `/studio/` and replaces the public game's ephemeral session adapter with a persistent, versioned engine service. It retains the existing original artwork and deterministic **math 0.8.0 baseline**. This document describes the implementation; successful deployment is established separately by CI, exact live-file verification and Railway terminal deployment receipts.

## Larger, continuous game controls

The lower console is one full-width scene with independent visible controls. It no longer scales three baked button strips into a small center panel. Spin measures 80–96 CSS pixels across supported phone layouts; Turbo/Auto are at least 52 pixels, and the smaller betting controls have at least 44-pixel touch targets. Compact portrait and landscape use explicit arrangements instead of shrinking every control with the artwork.

The continuous crown/logo, rounded lantern treatment and animated crown light remain in place. The game still uses 23 tiles with 2:3 faces. The background extends across the complete viewport and simulated notch/home areas, while interactive controls remain within safe insets. Mobile/simulated PWA screenshots and geometry assertions are part of browser verification; these simulations are not physical iPhone installation tests.

## Persistent rounds, tickets and credit ledger

The production web service uses Django, Gunicorn and PostgreSQL. A player session retains its virtual-credit balance, spin count and history across application restarts. The engine issues a ticket before Spin, pinning the release, rules, betting policy and seed commitment. A complete paid round includes all of its cascades, bonus spins and retriggers under that snapshot.

Each Spin carries its ticket ID and a client-generated UUID idempotency key. Database constraints, short row-locking transactions and a fenced computation claim prevent a consumed ticket from settling twice. A retry with the same ticket/key returns the stored response. A conflicting payload is rejected. Calculation happens outside the long settlement transaction; only a valid current claim can atomically write the round, debit/award, ledger entry, ticket consumption and next ticket.

Publishing while a player holds an existing ticket does not change that ticket's rules or offered stake denominations. Its next ticket adopts the active release. Presentation assets and audio remain pinned during the complete round. Rollback changes future tickets and retains past transcripts and balances. Historical replay evaluates the stored configuration; it fails explicitly if the matching evaluator is unavailable.

The old in-memory v0.8.x session cannot be recovered automatically. Its first new persistent session receives a migration notice. Old cached clients missing the required ticket/idempotency fields are rejected before debit. The PWA does not force a reload during an active round.

## Separate authenticated Game Studio

The custom React/TypeScript workspace contains Overview, Betting, Rules/Paytable, Tile Studio, Scene, Audio Studio, Math Lab, Releases, asset/job views and access/runtime information.

There are no default administrator credentials or public registration. The first owner is created through a private one-use activation link. After activation, that link cannot replace the owner. Owner, Editor and Tester capabilities are checked by the server; session authentication, CSRF protection, login/setup throttling and request-size limits apply to administrator operations. Merely sending a game API header is not administrator authentication.

Drafts have revision guards. Saving against an old revision returns a conflict instead of replacing another editor's changes. Validation receipts are bound to the draft/configuration and engine hash. Publish atomically activates a complete release bundle, and release history permits an authorized rollback with a recorded reason. Draft preview runs the real renderer in a separate test session, isolated from public player balances.

### Betting and rules

The editor supports offered/default virtual stakes, initial credits, Auto counts and stop policies; symbol weights; the 3/4/5-reel paytable; scatter/enhanced probabilities; base/bonus multipliers; free-spin awards; payout scales; and the cumulative round cap. The supported renderer remains the 4/5/5/5/4 grid with A–O ordinary symbols, W Wild and S Scatter. Weights must total 100. Numeric and structural bounds are validated server-side.

Big/Mega Win display thresholds and animation speed belong to presentation configuration. Changing artwork or a sound mapping does not change the probability calculation or payout multiple.

### Tile and scene editing

Tile Studio provides **34 mappings: 17 symbols × normal/gold**. Uploads retain their original bytes. Whole-tile and glyph modes, contain/cover, zoom, anchors and the gold ceramic body produce immutable 218×327 RGBA derivatives. Editing a tile never changes its mathematical symbol ID. The exact rendered derivative is selected for the mapping and used by the game renderer/atlas.

This release exposes four scene image slots: root background, crown, board and footer. Scene uploads are decoded and re-encoded before use. They do not add arbitrary executable HTML, scripts or new renderer layouts. More granular ornament, rail and typography editing from the wider plan is not a claim of this release.

### Audio Studio and runtime

Audio Studio provides a searchable clip library, actual per-clip waveform, time/playhead/zoom, live frequency spectrum and an on-demand spectrogram. It supports preview transport, loop selection, Raw/Recipe comparison, local recipe undo/redo, trim, fades, gain, pan, high-/low-pass and three-band EQ. Source and derivative remain separate. An explicit rendered-file player auditions the bytes that will be published, because browser DSP preview is not assumed to be identical to FFmpeg rendering.

The media worker produces a lossless 44.1 kHz WAV derivative with real waveform, sample peak/RMS and applicable LUFS/true-peak analysis. Short transient sounds show N/A for loudness analysis. Invalid trim/loop/fade ranges, unrecognized fields, malformed or oversized files and sample-clipping exports are rejected.

The runtime accepts the versioned audio manifest with **11 event groups**: tap, spin, stop, break, cascade, wild, multiplier, scatter, bonus, win and bigwin. The stop group retains per-reel pitch variation; this release does not expose five independent stop mappings. Scatter is triggered by the actual landed screen event. A dedicated Big Win clip may be assigned; the baseline retains its explicit shared win sound. Events can be disabled intentionally.

Music, Reels, Wins and UI buses feed one presentation output stage. The baseline **1.30× amplitude boost is applied once**, while existing player volume/music/mute preferences remain authoritative. Base and bonus tracks support loop ranges, with base music as the fallback when no bonus track is assigned. Fixed internal priorities, a 16-voice budget, short-event cooldowns and modest music ducking protect important effects during busy sequences. Configuration application does not wait for a music download; missing audio cannot block settlement. Caches, fetch/decode concurrency and cancellation are bounded.

These are application signal measurements, not hardware-volume guarantees. The mixer is not advertised as a certified true-peak limiter or full multitrack DAW. Physical iPhone/Android listening, loop-click assessment and combined-mix loudness remain device checks.

## Math Lab and publication evidence

Math Lab runs durable worker jobs with independent seed domains and reports paid-round sample count, estimated RTP, confidence interval, positive returns, returns at least equal to stake, bonus entry, cap hits, configuration/engine hashes and calculation failures. A paid-round result includes its bonus awards; bonus spins do not add a separate stake denominator.

Changed math requires a sufficient matching completed simulation before publication. A stale report for another draft/hash does not satisfy that gate. A target RTP is an analysis target, not a promise that each player or short session will receive that return. No per-player adaptive payout control was added.

The baseline imported by this release was **not recalibrated**. Existing math 0.8.0 audit results remain described in `docs/MATH_V080_VALIDATION.md`; they are estimates with uncertainty, not exact theoretical RTP or independent RNG certification. The deterministic evaluator retains Python MT19937 and the existing computation guards. The product remains a **virtual-credit game without deposits, withdrawals or prize redemption**.

## Worker, private storage and release operation

The web and worker use the same built image with separate process roles. Only the web role runs migrations/bootstrap; the worker waits for the schema and then processes persisted media/Math Lab jobs with leases and fencing. A database heartbeat allows `/health` and the release gate to report worker readiness. Expensive audio/image processing and simulation do not run inside public Spin requests.

Production requires PostgreSQL and a private S3-compatible bucket. Both process roles run a harmless content-addressed storage write/read/hash probe before entering normal operation. Media originals and derivatives use immutable hash keys, and published assets receive stable application URLs. Draft assets require authentication; bucket credentials and future seeds are not embedded in public JavaScript. Railway bucket addressing is configurable as `virtual` or `path`; storage configuration defaults to `virtual`.

The shared `railway.json` defines build/restart behavior. The web service's `/health` check is configured on that Railway service. The worker has no HTTP healthcheck because it is a worker process; its heartbeat and terminal deployment/log evidence are checked separately. A successful web HTTP response alone does not establish successful worker deployment.

The PWA service worker excludes Studio, API and uploaded-media routes from presentation caching. Versioned game files and the Studio bundle are built into the image. An old client is not allowed to submit a legacy unversioned Spin and debit credits silently.

### Backup and restore

`studio_backup` creates a private database-plus-object archive, and `studio_backup --verify` checks all hashes and references without restoring. `studio_restore` requires an empty migrated target and restores immutable bytes before an atomic database import. The round-trip tests include originals, derivatives, users/permissions/sessions, a completed round/ledger, a future ticket and identical retry/replay behavior. See `docs/STUDIO_BACKUP.md` for limits, secret handling, operator procedure and failure behavior.

These are operator commands. No automatic backup schedule or retention service is claimed. Retain the exact application build and environment secrets separately; the archive contains database records and uploaded media, not a replacement for deployment source or secret management.

## Build and verification

Build Studio with `npm ci && npm run build` in `studio_ui`, then compile the reviewed artwork/game derivatives in order:

```bash
python tools/build_locked_ui.py
python tools/build_presentation_fx.py
python tools/build_approved_ui.py
python tools/build_portrait_ui.py
python tools/build_responsive_runtime.py --runtime-only
python tools/build_fullframe_ui.py --runtime-only
python tools/build_studio_runtime.py
```

The original integrity-checked artwork/game sources are retained. Studio integration produces `assets/studio-v090/game.js`; the new audio runtime is a separate source asset. The `fullframe-v086` and `portrait-v085` names remain component families, while final HTML/cache/release metadata identify **UI 0.9.0**.

Verification includes existing engine/artwork/browser regressions; the larger-control layouts; PostgreSQL settlement, authorization, revision, publishing and concurrency tests; media decode/render/storage tests; backup/restore tests; and real browser integration in Chromium/WebKit. Audio graph tests verify the preserved 1.30 ratio, exact mute, event/bus/clip routing, voice priorities, stale-load cancellation and nonblocking behavior with missing music. PostgreSQL tests are required to establish row-lock behavior; SQLite tests alone do not establish it.

The main-branch live gate is:

```bash
MW_LIVE_URL=https://mahjong-legend-web-production.up.railway.app \
python tools/qa_studio_live_v090.py
```

It polls for at most eight minutes, checks the engine/PostgreSQL/worker health and exact built HTTP file hashes—including the game, full-frame layout, portrait reels, artwork and every compiled Studio chunk—then performs **one** real public UI Spin. It verifies the prior seed commitment, ticket/release pinning, one POST/one settlement, next ticket, reconciled persistent balance, final rendered board and server replay. It also checks the anonymous Studio screen and asset-library 401 response, plus a 390×690 screenshot and simulated 390×844 PWA safe areas.

The live gate never creates an owner, signs in, publishes, edits a draft or reconfigures infrastructure. It never automatically retries the Spin after an error. TLS verification is enabled by default. A proxy-environment certificate bypass is available only by explicit option, only after an observed certificate error, and is recorded in the receipt; it is not silently reported as verified TLS. Local rehearsal is separately labeled and requires an explicit localhost option.

The script writes a pass/fail receipt and screenshots. Its PASS establishes the checks it performed, **not Railway's terminal deployment status**. Final release reporting must also include the exact GitHub commit, completed CI and independent successful Railway web/worker deployment receipts. Owner activation remains a private user action through the one-use link; that token must not appear in this document, source control, QA logs or screenshots.
