"""Pixel-aligned logo light masks derived from the approved frame. No new lettering."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops
import hashlib, json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/locked-v08'

def build():
    frame=Image.open(OUT/'frame.webp').convert('RGB')
    if frame.size != (752,1338):
        raise ValueError('Unexpected locked frame coordinates')
    crop=frame.crop((222,60,532,189)).convert('RGBA')
    region=Image.new('L',crop.size)
    d=ImageDraw.Draw(region)
    # Top word and lower italic WILD. Exclude the jade roof/dragons/ways badge.
    d.polygon([(0,0),(302,0),(310,64),(25,64),(0,55)],fill=255)
    d.polygon([(36,54),(274,54),(254,123),(30,129)],fill=255)
    alpha=Image.new('L',crop.size);px=alpha.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r,g,b,_=crop.getpixel((x,y))
            # Select illuminated gold faces; do not lighten the red background.
            px[x,y]=max(0,min(255,round(min(r-140,g-80,r-b-35)*4)))
    alpha=ImageChops.multiply(alpha,region);crop.putalpha(alpha)
    (OUT/'effects').mkdir(exist_ok=True)
    crop.save(OUT/'effects/logo-emission.webp',lossless=True,method=6)
    mask=Image.new('RGBA',crop.size,'white');mask.putalpha(alpha)
    mask.save(OUT/'effects/logo-mask.webp',lossless=True,method=6)
    release=json.loads((OUT/'release.json').read_text())
    release['release']='0.8.1';release['math_version']='0.8.0'
    release['presentation']='smooth-strip-visible-shatter-pixel-aligned-neon'
    (OUT/'release.json').write_text(json.dumps(release,indent=2)+'\n')
    manifest=json.loads((OUT/'manifest.json').read_text())
    manifest.pop('presentation_version',None)
    extra={'version':'0.8.1','frame_sha256':hashlib.sha256((OUT/'frame.webp').read_bytes()).hexdigest(),'files':{}}
    for name in ('effects/logo-emission.webp','effects/logo-mask.webp'):
        f=OUT/name
        with Image.open(f) as im:size=im.size
        manifest['files'].pop(name,None)
        extra['files'][name]={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size,'size':size}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT/'presentation-manifest.json').write_text(json.dumps(extra,indent=2)+'\n')
    print('Built two pixel-aligned logo light masks; math configuration unchanged.')

if __name__=='__main__':build()
