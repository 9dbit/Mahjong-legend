"""UI 0.8.5: derive a taller board from approved art, never change the master.

Tile face width:height is 2:3 (218:327). Only the ceramic body is extended;
regular symbol layers keep their original pixel geometry. The top, lower
ornaments, meters and controls retain their original scale, translated below
the extended reel body. Game math and symbol identities are not changed.
"""
from pathlib import Path
import hashlib
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'web/assets/approved-v082'
OUT = ROOT / 'web/assets/portrait-v085'
HEIGHT = 1859
EXTENSION = HEIGHT - 1536

def save(image, path):
    target = OUT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, 'WEBP', lossless=True, method=1)

def build():
    OUT.mkdir(parents=True, exist_ok=True)
    frame = Image.open(SOURCE / 'frame.webp').convert('RGB')
    result = Image.new('RGB', (864, HEIGHT))
    # No scaling of the logo, numbers, corner ornaments or controls.
    # The vertical side-body section alone fills the new board height.
    upper, lower = 650, 920
    result.paste(frame.crop((0, 0, 864, upper)), (0, 0))
    result.paste(frame.crop((0, upper, 864, lower)).resize(
        (864, lower - upper + EXTENSION), Image.Resampling.LANCZOS), (0, upper))
    result.paste(frame.crop((0, lower, 864, 1536)), (0, lower + EXTENSION))
    save(result, 'frame.webp')
    for symbol in 'ABCDEFGHIJKLMNOWS':
        for state in ('normal', 'gold'):
            original = Image.open(SOURCE / f'tiles/{symbol}-{state}.webp').convert('RGBA')
            if symbol in 'WS':
                # Special badges occupy the whole original face.
                tile = original.resize((218, 327), Image.Resampling.LANCZOS)
            else:
                body = Image.open(SOURCE / ('tiles/base-gold.webp' if state == 'gold' else 'tiles/base-ivory.webp')).convert('RGBA')
                tile = body.resize((218, 327), Image.Resampling.LANCZOS)
                glyph = Image.open(SOURCE / f'symbols/{symbol}.webp').convert('RGBA')
                tile.alpha_composite(glyph, (0, 47))
            save(tile, f'tiles/{symbol}-{state}.webp')
    manifest = {'release': '0.8.5', 'math_version': '0.8.0', 'tile_size': [218, 327],
                'tile_ratio': [2, 3], 'frame_size': [864, HEIGHT], 'extension_px': EXTENSION,
                'source': 'web/assets/approved-v082/frame.webp',
                'source_sha256': hashlib.sha256((SOURCE / 'frame.webp').read_bytes()).hexdigest(),
                'files': {}}
    for p in sorted(OUT.rglob('*.webp')):
        manifest['files'][str(p.relative_to(OUT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (OUT / 'release.json').write_text(json.dumps({'release': '0.8.5', 'math_version': '0.8.0',
        'tile_ratio': '2:3', 'instant_input': True, 'virtual_credits_only': True}) + '\n')
    print('Portrait UI built:', len(manifest['files']), 'art assets; tile ratio 2:3')

if __name__ == '__main__':
    build()
