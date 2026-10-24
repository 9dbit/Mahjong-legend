# Mahjong Wild: Locked art and audio asset pack

## Scope and source

The locked design is 9:16 red lacquer, jade neon, gold-metal HDR, Chinese fantasy dragons mirrored left and right. The provided approved image is a flattened illustration, not a layered source. These are **reconstructed reusable sprites** (not precise original PNG layers). No marketing page is introduced. The wagering math and RNG package stays unchanged: internally its math configuration remains `Mahjong Legend` to preserve its hash.

## Asset hierarchy

```
web/assets/
  asset_manifest.json
  mahjong-wild.css             # Locked interface theme
  audio/player.js             # Sound and background music controller
  reference/locked_style_reference.webp
  tiles/base_ivory.webp
  tiles/base_gold.webp
  tiles/tile_A.webp ... tile_O.webp
  tiles/tile_W.webp            # WILD, substitution
  tiles/tile_S.webp            # SCATTER, triggers free spins
  symbols/symbol_A.webp ... symbol_O.webp
  symbols/symbol_W.webp, symbol_S.webp
  ornaments/dragon_left.webp, dragon_right.webp
  ornaments/lantern_left.webp, lantern_right.webp
  ornaments/cloud_left.webp, cloud_right.webp
  ui/logo.webp, header.webp, multiplier.webp, reel_backplate.webp,
     win_banner.webp, meter.webp, footer.webp,
     spin.webp, minus.webp, plus.webp, turbo.webp, auto.webp,
     menu.webp, sound.webp
  effects/cascade_glow.webp, wild_transform.webp, reel_spark.webp,
          bonus_flare.webp, win_aura.webp, scatter_burst.webp
  audio/music/ambient_jade_loop.ogg, ambient_jade_loop.m4a
  audio/sfx/spin.wav, reel_stop.wav, cascade.wav, tile_break.wav,
            wild.wav, multiplier.wav, scatter.wav, bonus.wav,
            win.wav, button.wav
```

## Tile lookup and functions

| Engine ID | Artwork | Function |
|---|---|---|
| A-D | 2 / 3 / 4 / 6 dots | Ordinary matching symbols |
| E-H | 2 / 3 / 4 / 6 bamboos | Ordinary matching symbols |
| I-L | 一萬 / 二萬 / 五萬 / 八萬 | Ordinary matching characters |
| M | 中 | Ordinary red-dragon character |
| N | 發 | Ordinary green-dragon character |
| O | 白 | Ordinary white-dragon character |
| W | WILD gold sycee | Substitutes compatible ordinary symbols |
| S | 福 | Scatter / free-spins trigger |

**Gold status** is a property of an ordinary tile, not a 16th regular matching symbol. It is represented by `base_gold.webp` and CSS overlay. During the winning cascade, eligible Gold tiles morph into Wild according to the math engine's events.

## Format and rendering

- Sprites are independent RGBA WebP with transparent backgrounds. These can be converted individually into PNG via Pillow without losing alpha.
- 17 complete tile sprites and 17 face-only symbol sprites allow separate layering.
- Sides use one mirrored dragon and lantern master for exact graphic symmetry.
- Reusable CSS and JSON manifests describe runtime paths and roles; effects are overlay sprites for CSS animations.
- Sound effects are original synthesized WAV; music is an original loop, exported as AAC (`.m4a`, Safari) and OGG.
- Music is off by default, and only starts after the player explicitly enables it in Settings and taps Spin.

## Rebuild

Requires Python, Pillow, NumPy, SciPy, ffmpeg and locally installed CJK serif fonts. Font binaries are not distributed in the pack. Run `python tools/build_assets.py` to regenerate, or use already exported runtime assets.

## QA

`python -m unittest discover -s tests -v` checks the engine, item inventory, alpha, mirroring, audio files.
Browser-based iPhone QA and audio playback on physical phones remain necessary before final production approval.