"""Build non-stretched dragon side ornaments from the approved Mahjong frame.

The master art, tile layout and math are unchanged.
"""
from pathlib import Path
import hashlib
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'web/assets/approved-v082/frame.webp'
OUT = ROOT / 'web/assets/ornament-v094'


def feather(image, inner_side, top, bottom, inner):
    image = image.convert('RGBA')
    width, height = image.size
    alpha = Image.new('L', image.size, 255)
    pixels = alpha.load()
    for y in range(height):
        y_alpha = min(1.0, (y + 1) / max(1, top), (height - y) / max(1, bottom))
        for x in range(width):
            distance = (width - 1 - x) if inner_side == 'right' else x
            x_alpha = min(1.0, max(0.0, distance / max(1, inner)))
            pixels[x, y] = round(255 * min(y_alpha, x_alpha))
    image.putalpha(alpha)
    return image


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as frame:
        assert frame.size == (864, 1536), 'Approved source dimensions changed'
        frame = frame.convert('RGB')
        specs = {
            'dragon-left': ((0, 394, 118, 1009), 'right', 230, 110, 19),
            'dragon-right': ((747, 394, 864, 1009), 'left', 230, 110, 19),
            'corner-left': ((0, 830, 200, 1009), 'right', 35, 0, 74),
            'corner-right': ((664, 830, 864, 1009), 'left', 35, 0, 74),
        }
        for name, (crop, inner_side, top, bottom, inner) in specs.items():
            img = feather(frame.crop(crop), inner_side, top, bottom, inner)
            img.save(OUT / (name + '.webp'), 'WEBP', lossless=True, method=1)
    manifest = {
        'release': 'ornament-v094', 'source': str(SOURCE.relative_to(ROOT)),
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'source_geometry': [864, 1536], 'non_scoring_art_only': True,
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(OUT.glob('*.webp'))},
    }
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Ornament v094 built: proportional dragons and feathered golden corners')


if __name__ == '__main__':
    build()
