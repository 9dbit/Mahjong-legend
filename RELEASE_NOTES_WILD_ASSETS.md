# Mahjong Wild v0.6: locked 9:16 asset-system integration

Brand/UI only. The mathematical engine, RNG, payout configuration and replay contract are unchanged. The backend math configuration retains its legacy project identifier for hash stability.

- 75 catalogued reusable sprites/audio entries, 78 deployable asset files in web/assets.
- Independently layered 17 complete WebP tile assets, 17 symbols (RGBA), 6 perfectly mirrored frame ornaments, 14 UI sprites and 6 effects sprites.
- One digital reference WebP preserving the approved 9:16 art direction.
- 10 synthesized WAV sound effects, one original ambient loop in M4A and OGG.
- Renderer now loads sprites from /assets/tiles/tile_<engineSymbol>.webp without changing event logic or outcomes.
- Backend serves only allowlisted MIME types under /assets/ with path traversal rejection.
- Music is opt-in, sound effects respect the original sound toggle and volume setting.
- The frontend label and API game title say "Mahjong Wild".

The composition reference is a flattened illustration. Generated alpha sprites are reconstructed independent assets, not original PSD layers.

Validation: `python -m unittest discover -s tests -q`, `python tools/verify_http_assets.py`. iPhone/Safari physical-device verification remains pending.