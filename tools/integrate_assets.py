"""Patch existing Mahjong Legend v0.4/v0.5 without touching math/round logic."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
h=ROOT/'web'/'index.html';s=h.read_text()
s=s.replace('Mahjong Legend','Mahjong Wild').replace('MAHJONG <strong>LEGEND</strong>','MAHJONG <strong>WILD</strong>')
s=s.replace('</head>','  <link rel="stylesheet" href="/assets/mahjong-wild.css?v=06">\n  <script src="/assets/audio/player.js?v=06" defer></script>\n</head>')
h.write_text(s)
j=ROOT/'web'/'app.js';src=j.read_text()
src=src.replace('Mahjong Legend','Mahjong Wild')
old='el.appendChild(tileFace(tile.symbol));'
new='''el.dataset.symbol=tile.symbol;
    const sprite=create('img','tile-image');
    sprite.src=`/assets/tiles/tile_${tile.symbol}.webp`;
    sprite.alt='';sprite.draggable=false;sprite.decoding='async';
    el.appendChild(sprite);'''
if old not in src:raise RuntimeError('Cannot find tile rendering hook')
src=src.replace(old,new)
needle='function playSound(tone) {'
if needle not in src:
    needle='function playSound(tone,variant=0) {'
    assert needle in src
src=src.replace(needle,needle+"\n    if (globalThis.MahjongWildAudio?.playSfx) {globalThis.MahjongWildAudio.playSfx(tone, 0, sound, typeof volume === 'number' ? volume : 0.65); return;}")
j.write_text(src)
p=ROOT/'mahjong_legend'/'server.py';src=p.read_text().replace('Mahjong Legend','Mahjong Wild')
# server v0.4 and current v0.5 can both support safe relative static assets
needle="        if path in ROUTES:\n"
patch="""        if path.startswith('/assets/'):
            relative = path[len('/assets/'):]
            if not relative or any(p in ('', '.', '..') for p in relative.split('/')):
                return self._json(404, {'error': 'Not found'})
            if not relative.lower().endswith(('.webp', '.png', '.wav', '.m4a', '.ogg', '.js', '.css', '.json')):
                return self._json(404, {'error': 'Not found'})
            root = (WEB / 'assets').resolve()
            target = (root / relative).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                return self._json(404, {'error': 'Not found'})
            mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            if target.suffix == '.js': mime = 'application/javascript'
            if target.suffix == '.m4a': mime = 'audio/mp4'
            if mime.startswith('text/') or mime == 'application/javascript': mime += '; charset=utf-8'
            return self._send(200, target.read_bytes(), mime)
"""
assert needle in src
src=src.replace(needle,patch+needle)
p.write_text(src)
print('Patched: HTML game title/asset links, JS tile/audio renderer, Python static asset server')