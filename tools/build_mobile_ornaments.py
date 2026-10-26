"""Source-faithful mobile-first layers for the Mahjong Legend portrait cabinet.

Each image remains a crop in original board-side pixels, never stretched or
rebuilt from a flattened game screenshot. CSS scales both axes identically.
The legacy full dragon columns remain available for landscape/desktop.
"""
from pathlib import Path
import hashlib
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# Pixel coordinates in the approved 118/117 x 938 side art, not CSS pixels.
CROPS = {'lantern': (0, 240), 'dragon': (200, 705), 'cloud': (600, 938)}


def _lantern_mask(width, side):
    mask = Image.new('L', (width, 240), 0)
    draw = ImageDraw.Draw(mask)
    def flip(x):
        return x if side == 'left' else width - 1 - x
    def box(x0, y0, x1, y1):
        return (min(flip(x0), flip(x1)), y0,
                max(flip(x0), flip(x1)), y1)
    # Round lantern, suspension fitting, and proportional red silk tassel.
    draw.rounded_rectangle(box(39, 0, 83, 44), radius=9, fill=255)
    draw.ellipse((6, 20, width - 4, 119), fill=255)
    draw.rounded_rectangle(box(36, 101, 86, 145), radius=10, fill=255)
    draw.rounded_rectangle(box(55, 136, 69, 165), radius=5, fill=255)
    draw.polygon([(flip(x), y) for x, y in
                  [(52, 150), (75, 150), (81, 238), (47, 238)]], fill=255)
    return mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.5))


def _body_mask(source, side):
    width = source.width
    top, bottom = CROPS['dragon']
    mask = Image.new('L', (width, bottom - top), 0)
    output, original = mask.load(), source.load()
    # Original gold body contour. Red areas and the straight gold side rail
    # should never be enlarged together with the dragon.
    bounds = [(200, 33, 76), (220, 23, 78), (250, 8, 86),
              (300, 10, 102), (350, 18, 105), (400, 27, 110),
              (450, 30, 111), (490, 35, 110), (515, 19, 110),
              (540, 8, 104), (590, 5, 98), (635, 10, 94),
              (670, 15, 96), (705, 18, 95)]
    def contour(y):
        for (y0, l0, r0), (y1, l1, r1) in zip(bounds, bounds[1:]):
            if y0 <= y <= y1:
                t = (y-y0)/(y1-y0)
                return l0+(l1-l0)*t, r0+(r1-r0)*t
        return bounds[-1][1:]
    for y in range(top, bottom):
        lo, hi = contour(y)
        for x in range(width):
            u = x if side == 'left' else width-1-x
            red, green, blue, _ = original[x, y]
            gold = (red > 88 and green > 27 and
                    red > green*1.12 and green > blue*.68)
            if lo <= u <= hi and gold and not (u >= 104 and y < 620):
                output[x, y-top] = 255
    mask = (mask.filter(ImageFilter.MaxFilter(15))
                .filter(ImageFilter.MinFilter(7))
                .filter(ImageFilter.GaussianBlur(1.65)))
    pixels = mask.load()
    for y in range(mask.height):
        opacity = min(1, (y+1)/40, (mask.height-y)/37)
        for x in range(width):
            pixels[x, y] = round(pixels[x, y]*opacity)
    return mask


def _cloud_mask(source):
    width = source.width
    top, bottom = CROPS['cloud']
    mask = Image.new('L', (width, bottom-top), 0)
    output, original = mask.load(), source.load()
    for y in range(top, bottom):
        for x in range(width):
            red, green, blue, _ = original[x, y]
            jade = green > 48 and green > red*.76 and blue > red*.67
            output[x, y-top] = 255 if jade else 0
    # Keep gold outlines / connected lower scrolls around the jade.
    return (mask.filter(ImageFilter.MaxFilter(27))
                .filter(ImageFilter.MinFilter(5))
                .filter(ImageFilter.GaussianBlur(1.8)))


def build_mobile_ornaments(out_dir: Path):
    """Produce six immutable derived sprites and an auditable manifest entry."""
    out_dir = Path(out_dir)
    products = []
    for side, original_width in [('left',118), ('right',117)]:
        source_path = out_dir / f'board-{side}.webp'
        source = Image.open(source_path).convert('RGBA')
        assert source.size == (original_width, 938), 'Approved side art drifted'
        for kind, mask in (
            ('lantern', _lantern_mask(original_width,side)),
            ('dragon', _body_mask(source,side)),
            ('cloud', _cloud_mask(source)),
        ):
            top,bottom = CROPS[kind]
            cut=source.crop((0,top,original_width,bottom))
            alpha=ImageChops.multiply(mask,cut.getchannel('A'))
            assert alpha.getextrema() == (0,255), (side,kind,'bad alpha')
            cut.putalpha(alpha)
            path=out_dir / f'mobile-{kind}-{side}.webp'
            cut.save(path,'WEBP',lossless=True,method=1)
            products.append(path)
    return {
        'source': 'portrait-v085/frame.webp / board left and right',
        'source_pixel_height': 938,
        'crops': {k:list(v) for k,v in CROPS.items()},
        'uniform_scale_only': True,
        'maximum_tile_overlap_fraction': .10,
        'desired_tile_overlap_fraction': .08,
        'files': {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in products},
    }
