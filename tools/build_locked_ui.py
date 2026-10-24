"""Build runtime sprites from the approved Mahjong Wild reference already in Git.

No downloaded artwork, random outcome changes, or runtime image processing.
Coordinates are recorded in the native 752x1338 reference coordinate system.
"""
from pathlib import Path
import hashlib
import json
import math
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'web/assets/locked-v08'
SOURCE = ROOT / 'web/assets/reference/locked_style_reference.webp'
SIZE = (752, 1338)


def save(im, name):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, 'WEBP', quality=95, method=6)


def gradient(im, box, top, bottom, radius=0):
    x0, y0, x1, y1 = box
    patch = Image.new('RGB', (x1-x0, y1-y0))
    draw = ImageDraw.Draw(patch)
    for y in range(patch.height):
        t = y/max(1, patch.height-1)
        c = tuple(round(a*(1-t)+b*t) for a,b in zip(top,bottom))
        draw.line((0,y,patch.width,y), fill=c)
    if radius:
        alpha=Image.new('L',patch.size);ImageDraw.Draw(alpha).rounded_rectangle((0,0,patch.width-1,patch.height-1),radius,fill=255)
        im.paste(patch,(x0,y0),alpha)
    else:
        im.paste(patch,(x0,y0))


def colored_cut(ref, box, channel):
    im=ref.crop(box).convert('RGBA')
    pixels=im.load()
    for y in range(im.height):
        for x in range(im.width):
            r,g,b,a=pixels[x,y]
            if channel=='red': score=min(r-1.65*g, r-1.4*b)
            elif channel=='green': score=g-max(r,b)
            elif channel=='blue': score=b-max(r,g)
            else: score=max(r,g,b)-min(r,g,b)
            alpha=max(0,min(255,round((score-16)*8)))
            pixels[x,y]=(r,g,b,alpha)
    return im


def overlay(base, art, box):
    x,y,w,h=box
    stamp=art.resize((w,h),Image.Resampling.LANCZOS)
    base.alpha_composite(stamp,(x,y))


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    ref=Image.open(SOURCE).convert('RGB')
    if ref.size != SIZE:
        raise ValueError(f'Expected locked reference {SIZE}, got {ref.size}')
    frame=ref.copy()
    # Remove the illustration's baked tiles, multiplier labels, sample win and
    # balances. These areas are rendered live; the surrounding approved art stays.
    gradient(frame,(90,325,662,916),(57,7,11),(92,15,12),14)
    gradient(frame,(91,245,661,305),(0,166,144),(0,63,61),12)
    gradient(frame,(132,936,621,998),(145,4,12),(102,2,11),7)
    for box in [(94,1040,241,1080),(345,1040,470,1080),(583,1040,711,1080)]:
        gradient(frame,box,(1,56,50),(1,32,32),3)
    save(frame,'frame.webp')
    # Keep a source crop for the central rotatable disk, without the dragon ring.
    disk=ref.crop((307,1128,444,1265)).convert('RGBA')
    circle=Image.new('L',disk.size);ImageDraw.Draw(circle).ellipse((0,0,136,136),fill=255)
    disk.putalpha(circle);save(disk,'spin-disc.webp')
    # Reuse the actual ceramic edges. Remove the sample pips with a smooth ivory
    # center; no symbol identity is inferred from the generative illustration.
    base=ref.crop((210,326,319,442)).convert('RGBA')
    gradient(base,(14,12,96,103),(239,233,217),(217,210,193),8)
    alpha=Image.new('L',base.size);ImageDraw.Draw(alpha).rounded_rectangle((1,1,108,115),11,fill=255)
    base.putalpha(alpha)
    base=base.resize((218,232),Image.Resampling.LANCZOS)
    gold=ImageOps.colorize(ImageOps.grayscale(base),(127,48,0),(255,235,100)).convert('RGBA');gold.putalpha(base.getchannel('A'))
    save(base,'tiles/base-ivory.webp');save(gold,'tiles/base-gold.webp')
    blue=colored_cut(ref,(341,333,373,365),'blue')
    green=colored_cut(ref,(378,332,412,366),'green')
    red=colored_cut(ref,(359,360,393,391),'red')
    # Round masks preserve the engraved white pinpoints inside every colored pip.
    for art,box in [(blue,(341,333,373,365)),(green,(378,332,412,366)),(red,(359,360,393,391))]:
        original=ref.crop(box).convert('RGBA');mask=Image.new('L',art.size)
        d=ImageDraw.Draw(mask);d.ellipse((2,2,art.width-3,art.height-3),fill=255)
        original.putalpha(mask);art.paste(original,(0,0))
    bamboo=colored_cut(ref,(478,459,496,495),'green')
    bamboo_red=ImageOps.colorize(ImageOps.grayscale(bamboo),(85,0,0),(237,50,15)).convert('RGBA');bamboo_red.putalpha(bamboo.getchannel('A'))
    red_dragon=colored_cut(ref,(228,572,299,659),'red')
    # Keep the connected ruby glyph, not isolated orange/gold flourishes nearby.
    a=red_dragon.getchannel('A');pixels=a.load();seen=set();parts=[]
    for y in range(a.height):
        for x in range(a.width):
            if pixels[x,y]<100 or (x,y) in seen:continue
            group=[];todo=[(x,y)];seen.add((x,y))
            while todo:
                xx,yy=todo.pop();group.append((xx,yy))
                for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                    nx,ny=xx+dx,yy+dy
                    if 0<=nx<a.width and 0<=ny<a.height and (nx,ny) not in seen and pixels[nx,ny]>=100:
                        seen.add((nx,ny));todo.append((nx,ny))
            parts.append(group)
    if parts:
        clean=Image.new('L',a.size);cp=clean.load()
        for x,y in max(parts,key=len):cp[x,y]=pixels[x,y]
        red_dragon.putalpha(clean)
    green_dragon=colored_cut(ref,(336,570,419,666),'green')
    white_dragon=colored_cut(ref,(119,635,185,724),'blue')
    eight=colored_cut(ref,(238,458,288,488),'blue')
    wan=colored_cut(ref,(237,490,287,546),'red')
    sym={}
    for letter,count in zip('ABCD',[2,3,4,6]):
        art=Image.new('RGBA',base.size)
        pos={2:[(49,42),(130,132)],3:[(39,30),(90,89),(141,148)],4:[(42,40),(124,40),(42,132),(124,132)],6:[(29,41),(85,41),(141,41),(29,135),(85,135),(141,135)]}[count]
        for i,(x,y) in enumerate(pos): overlay(art,[blue,green,red][i%3],(x,y,46,46))
        sym[letter]=art
    for letter,count in zip('EFGH',[2,3,4,6]):
        art=Image.new('RGBA',base.size)
        pos={2:[(61,70),(132,70)],3:[(40,38),(92,89),(144,137)],4:[(52,40),(134,40),(52,128),(134,128)],6:[(31,37),(93,37),(155,37),(31,126),(93,126),(155,126)]}[count]
        for i,(x,y) in enumerate(pos):overlay(art,bamboo_red if i==1 else bamboo,(x,y,27,65))
        sym[letter]=art
    # Existing engine symbol overlays supply missing numerals (1,2,5). This keeps
    # all 15 distinct symbol IDs and their paytable entries, not invented aliases.
    for letter in 'IJK':
        art=Image.open(ROOT/f'web/assets/symbols/symbol_{letter}.webp').convert('RGBA')
        canvas=Image.new('RGBA',base.size);art.thumbnail((152,178),Image.Resampling.LANCZOS)
        canvas.alpha_composite(art,((218-art.width)//2,(232-art.height)//2));sym[letter]=canvas
    for letter,art,box in [('L',eight,(59,42,100,53)),('M',red_dragon,(43,28,134,172)),('N',green_dragon,(39,25,142,180)),('O',white_dragon,(45,25,128,181))]:
        canvas=Image.new('RGBA',base.size);overlay(canvas,art,box)
        if letter=='L':overlay(canvas,wan,(64,100,90,105))
        sym[letter]=canvas
    for letter,art in sym.items():
        save(art,f'symbols/{letter}.webp')
        for state,body in [('normal',base),('gold',gold)]:
            tile=body.copy();tile.alpha_composite(art);save(tile,f'tiles/{letter}-{state}.webp')
    wild=ref.crop((321,443,430,557)).convert('RGBA').resize(base.size,Image.Resampling.LANCZOS)
    wild.putalpha(base.getchannel('A'));save(wild,'tiles/W-normal.webp');save(wild,'tiles/W-gold.webp')
    scatter=gold.copy()
    f=Image.open(ROOT/'web/assets/symbols/symbol_S.webp').convert('RGBA');f.thumbnail((134,158),Image.Resampling.LANCZOS)
    scatter.alpha_composite(f,((218-f.width)//2,(232-f.height)//2))
    save(scatter,'tiles/S-normal.webp');save(scatter,'tiles/S-gold.webp')
    # Separate alpha shards and crack overlay for the event-driven break effect.
    crack=Image.new('RGBA',base.size);d=ImageDraw.Draw(crack)
    routes=[[(108,116),(83,77),(111,49),(96,0)],[(108,116),(144,91),(170,103),(217,66)],[(108,116),(129,154),(115,182),(153,232)],[(108,116),(73,146),(36,132),(0,165)]]
    for route in routes:d.line(route,fill=(79,44,18,215),width=3);d.line([(x+2,y) for x,y in route],fill=(255,242,180,210),width=1)
    save(crack,'effects/crack.webp')
    for i in range(8):
        shard=Image.new('RGBA',(64,64));p=ImageDraw.Draw(shard)
        points=[(5,18),(23+(i%3)*5,3),(56,15+i*2),(48,48),(12,57)]
        p.polygon([(x,y+5) for x,y in points],fill=(145,92,23,255));p.polygon(points,fill=(243,236,213,255));p.line(points+[points[0]],fill=(255,253,232,255),width=2)
        p.line([(12,54),(48,46)],fill=(10,95,55,255),width=4);save(shard,f'effects/shard-{i}.webp')
    paths=sorted(p for p in OUT.rglob('*.webp'))
    manifest={'version':'0.8.0','source':str(SOURCE.relative_to(ROOT)),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'coordinate_size':SIZE,'renderer':'live-reels-over-locked-art','artwork_note':'Reference crops/composites; not original 3D models or extracted hidden layers. Missing numerals retain legacy symbol overlays.','files':{str(p.relative_to(OUT)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'size':Image.open(p).size} for p in paths}}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT/'release.json').write_text(json.dumps({'release':'0.8.0','base_multipliers':[1,2,3,5],'bonus_multipliers':[2,3,5,8],'rtp_status':'not_revalidated_after_base_multiplier_change','virtual_credits_only':True})+'\n')
    print(f'Built {len(paths)} locked-style WebP files from existing source reference.')

if __name__=='__main__':build()
