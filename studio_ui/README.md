# Mahjong Legend Game Studio

Custom React/TypeScript administration interface. Its public entry point is `/studio/`; all state is read from the authenticated Django `/api/studio` endpoints. There are no production credentials or fabricated API responses in this bundle.

## Build

Requires Node 22.12+ (or Node 24). Dependencies are pinned in `package-lock.json`.

```sh
cd studio_ui
npm ci
npm run build
```

The build writes `../web/studio/index.html` and content-hashed assets under `../web/studio/assets`. The Python application serves them; Vite is not used in production. `npm run check` performs strict TypeScript validation. Local development uses `npm run dev`, with API and asset requests proxied to port 8080.

## Implemented workflows

- One-time owner activation from `#setup=<token>`; the token is removed from the address bar before the UI renders. The owner selects a username and strong password. Standard login/logout uses Django session/CSRF protection.
- Create/select drafts, edit, save with revision preconditions, validate, preview, publish with a reason, and activate an earlier immutable release. A conflict retains unsaved local changes and offers an explicit reload of the server revision.
- Decimal/string denominations, virtual balance, Auto settings, presentation thresholds, symbol weights and 3/4/5-reel paytable, cascade ladders, scatter/enhanced/free-spin parameters, scales and cap.
- 17 tile identities with normal/gold bindings, tile upload, crop/contain/cover/anchor/zoom/glyph recipes, and asynchronous derivative rendering. Scene images have a separate upload and binding workflow.
- Audio library, real PCM/decoded waveforms, seek/zoom/playhead, playback spectrum, on-demand spectrogram, source peak/RMS, server loudness/true-peak metadata, trim/fade/gain/pan/filters/three EQ bands, undo/redo, raw versus recipe audition, exact rendered-file audition, event bindings, mixer buses and base/bonus music.
- Math Lab job queue, cancel, source-backed RTP/95% interval/positive-payout/return-at-least-stake/bonus metrics, immutable config and engine hashes, full JSON report.
- Actual game preview in an isolated session with compact, portrait, and landscape viewport presets. Preview labels physical PWA and listening checks separately.

## Media behavior

Only verified Ready derivatives may be assigned. Original uploads are retained privately by the backend. Baseline audio references are derived from the current config. Small known baseline PCM WAVs get real mini-waveforms without allocating the entire decoded library; the active editor decodes one source at a time. BGM decoding is deferred until selection. Baseline clips are imported explicitly before editing.

Rendering starts from the retained original. When editing an existing audio derivative, the editor selects its neutral ingestion derivative as the raw audition source, restores the saved recipe, and offers a separate player for the exact selected rendered bytes. If that neutral source is unavailable in the returned library, recipe playback/rendering is unavailable rather than applying effects twice. Browser audition is approximate; the server-rendered file is the publication artifact. Waveform/spectrum processing stops when hidden and playback is stopped when the audio page unmounts.

Tile transform previews are composition guides. The selected worker derivative is the final reference for publication. Images keep the runtime 218 × 327 contract.

## API alignment

Requests and response types live in `src/api.ts` and `src/types.ts`. Mutating calls send the CSRF token from `/api/studio/session`; draft mutations also send `If-Match`. Only `edit`, `test`, and `publish` permissions expose enabled actions, and the backend enforces them independently. The Studio service worker is not registered by this application.

`/api/studio/assets/import-baseline` accepts only allowlisted paths. Upload kinds are `tile`, `scene`, and `audio`. Render recipes use the exact keys implemented by `game_studio.media`. Math Lab percentage fields use 100 to mean 100%, and the seed-domain input is a label; validation domains are generated independently by the server.

## Browser verification

`qa_studio.py` starts a disposable database and Django process, creates a temporary owner through the real setup form, exercises drafts and asset/audio rendering, runs a small exploratory simulation, and verifies preview/publication/rollback. It does not connect to production or use existing administrators. Run after the full game build and the Studio build, with Django, Pillow, FFmpeg and Playwright browsers installed:

```sh
python studio_ui/qa_studio.py --engine chromium --output qa/studio-v090/chromium
python studio_ui/qa_studio.py --engine webkit --output qa/studio-v090/webkit
```

The QA report excludes temporary credentials and setup tokens. `--web-root` can select an isolated complete build.
