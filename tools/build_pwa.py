"""Package existing approved logo art for Home Screen and declare display scope.

These are installation icons only; the locked game frame is never modified.
The game remains online and API responses are never cached by a service worker.
"""
from pathlib import Path
import io
import json
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'web/assets/locked-v08'


def build():
    # The logo already exists in the approved runtime source pack.
    logo = Image.open(ROOT / 'web/assets/ui/logo.webp').convert('RGBA')
    for size in (180, 192, 512):
        canvas = Image.new('RGBA', (size, size), '#160507')
        art = ImageOps.contain(logo, (round(size * .9), round(size * .9)), Image.Resampling.LANCZOS)
        canvas.alpha_composite(art, ((size-art.width)//2, (size-art.height)//2))
        buffer = io.BytesIO()
        canvas.convert('RGB').save(buffer, 'PNG', optimize=True)
        (OUT/f'app-icon-{size}.png').write_bytes(buffer.getvalue())
    manifest = {
        'id': '/', 'name': 'Mahjong Wild — Mahjong Legend', 'short_name': 'Mahjong Wild',
        'description': 'Mahjong cascade dengan kredit virtual.', 'lang': 'id',
        'start_url': '/?launch=pwa', 'scope': '/', 'display': 'standalone',
        'background_color': '#160507', 'theme_color': '#160507',
        'icons': [{'src': f'/assets/locked-v08/app-icon-{size}.png', 'sizes': f'{size}x{size}',
                   'type': 'image/png', 'purpose': 'any'} for size in (192, 512)]
    }
    (OUT/'manifest.webmanifest').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print('Built Home Screen icons and standalone PWA manifest.')


if __name__ == '__main__':
    build()
