# Mahjong Wild 0.8.0

## Scope
Playable 9:16 game UI using the user's approved symmetrical gold-dragon artwork.
No marketing page. Virtual credits only; no deposit, withdrawal or prize redemption.

## Artwork and runtime
The locked artwork already in `web/assets/reference/locked_style_reference.webp`
is the reproducible source. `tools/build_locked_ui.py` creates 62 individual WebP
assets: a cleared ornamental frame, tile bodies and separate symbols, normal/gold
tile states, a rotating spin disk, crack overlay and eight alpha shards. The source
image's baked sample payouts, balances, tiles and multiplier labels are removed.
All displayed outcomes, balances and multipliers come from the existing game API.

This is a crop-and-composite pipeline, not extraction of original hidden 3D layers.
Missing 1/2/5 numerals retain the existing symbol overlays, preserving 15 distinct
regular engine symbols. Generated sprites and their hash manifest are rebuilt by
CI and the Docker build; the build script and input assets are tracked in Git.

`web/assets/locked-v08/game.js`, `game.css` and `audio.js` implement the runtime.
Existing music and WAV files remain in `web/assets/audio/`. Audio is unlocked by a
user gesture. Music defaults to off. Mute, volume and hidden-tab behavior are handled.
Winning ordinary tiles crack then shatter; winning enhanced tiles transform into
Wild rather than being removed. Skip never submits a second paid request. Reduced
motion is supported. The original public-session backend is retained.

## User-approved mathematics change
Base cascade multipliers: **1, 2, 3, 5** (previously 1, 2, 3, 4).
Bonus multipliers remain **2, 3, 5, 8**. Other probability, paytable scale, free-spin
and cap settings are unchanged. Math config version is 0.8.0, with a new hash.
Prior RTP estimates are NOT valid claims for this configuration. No new theoretical
or Monte Carlo RTP is claimed in this release. Old-rule replay rejection is tested.
The independent legacy reference test explicitly uses the old ladder; new tests
separately prove the x5 payout and exact uncapped delta for a controlled fixture.

## Verification
Run `python tools/build_locked_ui.py`, then `python -m unittest discover -s tests -q`.
Run `python tools/qa_locked_ui.py` for real local HTTP browser checks. `--offline`
embeds assets and binds API requests to the real Python engine for environments
that prohibit browser localhost navigation; it is not an external HTTP test.
Test seeds exist only in the test process; no fixture override is exposed publicly.
Browser coverage: 320x568, 375x667, 390x844, 430x932, 1440x900; x5 cascade, Gold-to-Wild,
bonus, loss, replay validation, reduced motion, audio unlock, skip without double spin.
Physical iPhone speaker quality and device frame rate require separate device QA.
