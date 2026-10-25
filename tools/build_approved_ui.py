"""Compile the exact user-approved 864x1536 artwork into real runtime layers.

Only placeholder regions are cleared. Original source pixels remain unchanged
elsewhere. No generated substitute artwork, gameplay RNG, or math edits.
"""
from pathlib import Path
import hashlib, json, math
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageChops

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'web/assets/reference/approved_pwa_20261024.jpg'
OUT=ROOT/'web/assets/approved-v082'
SIZE=(864,1536)

def save(im,name):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    im.save(p,'WEBP',lossless=True,method=1)

def grad(size,top,bottom):
    im=Image.new('RGB',size);d=ImageDraw.Draw(im)
    for y in range(size[1]):
        t=y/max(1,size[1]-1)
        d.line((0,y,size[0],y),fill=tuple(round(a*(1-t)+b*t) for a,b in zip(top,bottom)))
    return im

def patch(im,box,top,bottom,radius=0):
    x,y,x1,y1=box;g=grad((x1-x,y1-y),top,bottom)
    if radius:
        m=Image.new('L',g.size);ImageDraw.Draw(m).rounded_rectangle((0,0,g.width-1,g.height-1),radius,fill=255);im.paste(g,(x,y),m)
    else:im.paste(g,(x,y))

def cut(ref,box,kind):
    im=ref.crop(box).convert('RGBA');p=im.load()
    for y in range(im.height):
        for x in range(im.width):
            r,g,b,_=p[x,y]
            score={'red':min(r-g*1.58,r-b*1.55),'green':g-max(r,b)*1.05,'blue':b-max(r,g)*1.05}[kind]
            p[x,y]=(r,g,b,max(0,min(255,round((score-10)*10))))
    return im

def stamp(base,art,box):
    x,y,w,h=box;base.alpha_composite(art.resize((w,h),Image.Resampling.LANCZOS),(x,y))

def glyph_depth(art):
    a=art.getchannel('A');out=Image.new('RGBA',art.size)
    sh=Image.new('RGBA',art.size,(45,17,6,0));sh.putalpha(a.point(lambda x:int(x*.55)).filter(ImageFilter.GaussianBlur(1)))
    out.alpha_composite(sh,(1,3));out.alpha_composite(art)
    return out

def largest_shape(im):
    a=im.getchannel('A');pixels=a.load();seen=set();groups=[]
    for y in range(im.height):
        for x in range(im.width):
            if pixels[x,y]<80 or (x,y) in seen:continue
            stack=[(x,y)];seen.add((x,y));group=[]
            while stack:
                xx,yy=stack.pop();group.append((xx,yy))
                for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                    nx,ny=xx+dx,yy+dy
                    if 0<=nx<im.width and 0<=ny<im.height and pixels[nx,ny]>=80 and (nx,ny) not in seen:
                        seen.add((nx,ny));stack.append((nx,ny))
            groups.append(group)
    if groups:
        m=Image.new('L',im.size);mp=m.load()
        for x,y in max(groups,key=len):mp[x,y]=pixels[x,y]
        im.putalpha(m)
    return im

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    ref=Image.open(SOURCE).convert('RGB');assert ref.size==SIZE
    frame=Image.open(ROOT/'web/assets/reference/approved_pwa_native_status.webp').convert('RGB')
    # Remove the mockup clock/battery; the OS draws the real status bar.
    # Interpolate adjacent sky rows rather than reproducing fake device data.
    # Runtime board. The low corner cloud/scrollwork is left intact.
    board=grad((630,615),(64,7,10),(104,16,10));mask=Image.new('L',SIZE)
    ImageDraw.Draw(mask).polygon([(118,394),(747,394),(747,941),(685,957),(648,1009),(218,1009),(177,978),(118,954)],fill=255)
    # The lower approved gold scrollwork extends across the tapered board edge.
    # A hard binary polygon made it look cut off by a dark rectangular panel.
    # Feather only the lower corners; preserve the locked top/side frame geometry.
    blurred=mask.filter(ImageFilter.GaussianBlur(18))
    feather_ramp=Image.new('L',SIZE,0)
    fade_draw=ImageDraw.Draw(feather_ramp)
    for y in range(820,1028):
        blend=max(0,min(255,round(255*(y-820)/68)))
        fade_draw.line((0,y,SIZE[0],y),fill=blend)
    fade_draw.rectangle((0,1028,SIZE[0],SIZE[1]),fill=255)
    mask=Image.composite(blurred,mask,feather_ramp)
    assert 40 < mask.getpixel((153,968)) < 220, 'Lower left scroll feather missing'
    assert 40 < mask.getpixel((709,950)) < 220, 'Lower right scroll feather missing'
    layer=frame.copy();layer.paste(board,(118,394));frame.paste(layer,(0,0),mask)
    patch(frame,(108,315,756,375),(0,128,112),(0,49,48),12)
    patch(frame,(157,1028,711,1098),(128,0,9),(91,0,9),10)
    for box in [(118,1149,282,1188),(398,1149,543,1188),(658,1149,820,1188)]:patch(frame,box,(0,59,51),(0,31,29),4)
    # Erase the fixed arrow disc underneath the rotating real control.
    disc_box=(349,1224,515,1390);disc=ref.crop(disc_box).convert('RGBA')
    m=Image.new('L',disc.size);ImageDraw.Draw(m).ellipse((1,1,164,164),fill=255);disc.putalpha(m)
    plain=grad(disc.size,(0,170,144),(0,73,66));frame.paste(plain,disc_box[:2],m)
    save(frame,'frame.webp');save(disc,'spin-disc.webp')
    # Reflect only the sky/cloud margins into device surplus area, no UI controls.
    save(ImageOps.flip(frame.crop((0,0,864,47))),'extension-top.webp')
    save(ImageOps.flip(frame.crop((0,1480,864,1536))),'extension-bottom.webp')
    # Extended viewport uses only red sky and side clouds, never duplicated UI.
    backdrop=grad(SIZE,(89,7,22),(113,16,16)).convert('RGBA')
    for box,dest in [((0,1460,200,1536),(0,1390)),((664,1460,864,1536),(664,1390))]:
        cloud=ref.crop(box).convert('RGBA').resize((200,146),Image.Resampling.LANCZOS)
        alpha=Image.new('L',cloud.size);ap=alpha.load()
        for y in range(cloud.height):
            for x in range(cloud.width):ap[x,y]=int(130*min(1,y/90))
        cloud.putalpha(alpha);backdrop.alpha_composite(cloud,dest)
    save(backdrop,'backdrop.webp')
    save(ref.crop((12,1210,120,1355)),'red-texture.webp')
    # Logo shine is a mask aligned to the actual approved gold lettering.
    logo=ref.crop((253,123,611,258)).convert('RGBA');alpha=Image.new('L',logo.size);ap=alpha.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r,g,b,_=logo.getpixel((x,y));ap[x,y]=max(0,min(255,round(min(r-135,g-80,g-b*1.25)*4)))
    light=Image.new('RGBA',logo.size,(255,204,76,255));light.putalpha(alpha)
    white=Image.new('RGBA',logo.size,(255,255,255,255));white.putalpha(alpha)
    save(light,'logo-emission.webp');save(white,'logo-mask.webp')
    for value,box in [(1,(153,308,249,377)),(2,(310,317,400,376)),(3,(465,317,555,376)),(5,(620,317,712,376))]:
        glyph=ref.crop(box).convert('RGBA');am=Image.new('L',glyph.size);amap=am.load()
        for y in range(glyph.height):
            for x in range(glyph.width):
                r,g,b,_=glyph.getpixel((x,y))
                ok=(r>170 and g>115 and r>g*1.1) if value==1 else (g>155 and b>100 and g>r*1.45)
                if ok:amap[x,y]=255
        if value==1:
            am=Image.new('L',glyph.size);d=ImageDraw.Draw(am)
            for poly in [[(176,325),(186,327),(188,335),(201,324),(212,325),(212,333),(194,349),(202,365),(200,371),(180,371),(176,360),(166,372),(155,370),(154,362),(173,345),(169,329)],[(211,317),(241,308),(247,311),(236,356),(243,358),(241,372),(204,372),(203,363),(208,354),(214,354),(220,328),(211,331),(207,324)]]:
                d.polygon([(x-box[0],y-box[1]) for x,y in poly],fill=255)
        am=am.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(.5));glyph.putalpha(am)
        for active in [False,True]:
            if (value==1)==active:colored=glyph.copy()
            else:
                colored=ImageOps.colorize(ImageOps.grayscale(glyph),(80,25,0) if active else (0,34,31),(255,236,111) if active else (71,255,227)).convert('RGBA');colored.putalpha(am)
            save(colored,f'multiplier/{value}-'+('active' if active else 'idle')+'.webp')
    # Normal ceramic body: retain the source tile bevel and edge reflection.
    base=ref.crop((249,395,373,519)).convert('RGBA')
    # Clear all pips, not only their centers. Feather into the original ceramic rim.
    face=grad((104,108),(243,235,217),(220,209,190)).convert('RGBA')
    fm=Image.new('L',face.size);ImageDraw.Draw(fm).rounded_rectangle((1,1,102,106),9,fill=255)
    fm=fm.filter(ImageFilter.GaussianBlur(2));base.paste(face,(10,8),fm)
    mask=Image.new('L',base.size);ImageDraw.Draw(mask).rounded_rectangle((1,1,122,122),13,fill=255);base.putalpha(mask)
    base=base.resize((218,232),Image.Resampling.LANCZOS)
    gold=ref.crop((375,638,496,762)).convert('RGBA').resize((218,232),Image.Resampling.LANCZOS)
    # Preserve ornamental corners, clear only the central sample glyph.
    patch(gold,(19,18,200,212),(255,224,62),(249,171,16),14);gold.putalpha(base.getchannel('A'))
    save(base,'tiles/base-ivory.webp');save(gold,'tiles/base-gold.webp')
    pips=[]
    for box in [(316,469,347,501),(273,415,305,447),(295,442,326,474)]:
        p=ref.crop(box).convert('RGBA');a=Image.new('L',p.size);ImageDraw.Draw(a).ellipse((2,2,p.width-3,p.height-3),fill=255);p.putalpha(a);pips.append(p)
    bamboo=cut(ref,(548,527,568,568),'green')
    bred=ImageOps.colorize(ImageOps.grayscale(bamboo),(90,0,0),(208,28,12)).convert('RGBA');bred.putalpha(bamboo.getchannel('A'))
    symbols={}
    for letter,count in zip('ABCD',[2,3,4,6]):
        art=Image.new('RGBA',base.size)
        coords={2:[(47,40),(128,138)],3:[(32,26),(86,90),(140,154)],4:[(38,36),(128,36),(38,140),(128,140)],6:[(24,36),(86,36),(148,36),(24,146),(86,146),(148,146)]}[count]
        for i,(x,y) in enumerate(coords):stamp(art,pips[i%3],(x,y,46,46))
        symbols[letter]=art
    for letter,count in zip('EFGH',[2,3,4,6]):
        art=Image.new('RGBA',base.size)
        coords={2:[(92,26),(92,130)],3:[(38,35),(92,90),(146,145)],4:[(50,35),(140,35),(50,134),(140,134)],6:[(28,35),(94,35),(157,35),(28,134),(94,134),(157,134)]}[count]
        for i,(x,y) in enumerate(coords):stamp(art,bred if i==1 and count>2 else bamboo,(x-4,y-5,34,78))
        symbols[letter]=art
    for letter in 'IJK':
        # Retain the already approved asset for numerals absent from this mockup.
        art=Image.open(ROOT/f'web/assets/symbols/symbol_{letter}.webp').convert('RGBA');art.thumbnail((145,180),Image.Resampling.LANCZOS)
        s=Image.new('RGBA',base.size);s.alpha_composite(art,((218-art.width)//2,(232-art.height)//2));symbols[letter]=s
    for letter,box,kind,target in [
        ('M',(650,838,723,934),'red',(45,27,130,177)),
        ('N',(390,650,480,752),'green',(35,26,149,180)),
        ('O',(145,718,221,808),'blue',(43,29,131,175)),
        ('L',(274,529,343,566),'blue',(49,31,123,63))]:
        art=Image.new('RGBA',base.size);piece=cut(ref,box,kind)
        if letter=='M':piece=largest_shape(piece)
        stamp(art,piece,target)
        if letter=='L':stamp(art,cut(ref,(287,567,337,624),'red'),(64,103,92,104))
        symbols[letter]=art
    for letter,art in symbols.items():
        save(art,f'symbols/{letter}.webp')
        for state,body in [('normal',base),('gold',gold)]:
            tile=body.copy();tile.alpha_composite(glyph_depth(art));save(tile,f'tiles/{letter}-{state}.webp')
    wild=ref.crop((375,519,496,637)).convert('RGBA').resize(base.size,Image.Resampling.LANCZOS);wild.putalpha(base.getchannel('A'))
    for state in ['normal','gold']:save(wild,f'tiles/W-{state}.webp')
    scatter=gold.copy();stamp(scatter,Image.open(ROOT/'web/assets/symbols/symbol_S.webp').convert('RGBA'),(35,33,148,168))
    for state in ['normal','gold']:save(scatter,f'tiles/S-{state}.webp')
    # Use complete source tile faces wherever the exact visual identity is present.
    # The engine still has all original distinct IDs and unchanged probabilities.
    for key,box in [('B',(249,395,373,519)),('E',(499,518,624,638)),('L',(249,519,373,638)),('M',(629,828,747,949)),('O',(119,707,245,824))]:
        tile=ref.crop(box).convert('RGBA').resize(base.size,Image.Resampling.LANCZOS)
        tile.putalpha(base.getchannel('A'));save(tile,f'tiles/{key}-normal.webp')
    for key,box in [('M',(249,640,373,765)),('N',(375,638,496,762))]:
        tile=ref.crop(box).convert('RGBA').resize(base.size,Image.Resampling.LANCZOS)
        tile.putalpha(base.getchannel('A'));save(tile,f'tiles/{key}-gold.webp')
    # A bold branching ceramic crack, not a symbol replacement.
    crack=Image.new('RGBA',base.size);d=ImageDraw.Draw(crack)
    for pts in [[(105,112),(80,75),(95,48),(75,0)],[(105,112),(145,83),(167,100),(218,68)],[(105,112),(130,158),(117,187),(157,232)],[(105,112),(70,146),(36,128),(0,166)]]:
        d.line(pts,fill=(58,32,13,235),width=4);d.line([(x+2,y-1) for x,y in pts],fill=(255,236,159,235),width=2)
    save(crack,'effects/crack.webp')
    # PWA icons from the approved seal, not a replacement brand.
    for n in [180,192,512]:
        icon=ref.crop((354,48,511,205)).resize((n,n),Image.Resampling.LANCZOS)
        icon.save(OUT/f'icon-{n}.png')
    files={str(p.relative_to(OUT)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(OUT.rglob('*')) if p.is_file() and p.suffix in ['.webp','.png','.m4a','.ogg','.wav']}
    manifest={'ui_version':'0.8.3','math_version':'0.8.0','source':str(SOURCE.relative_to(ROOT)),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'coordinate_size':SIZE,'note':'Exact source frame outside live placeholders. Symbols remain distinct. Device status indicators are native, never baked.','files':files}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT/'release.json').write_text(json.dumps({'release':'0.8.3','math_version':'0.8.0','base_multipliers':[1,2,3,5],'bonus_multipliers':[2,3,5,8],'rtp_status':'not_revalidated_after_base_multiplier_change','virtual_credits_only':True})+'\n')
    print('Approved source compiled:',len(files),'assets; math unchanged.')
if __name__=='__main__':build()
