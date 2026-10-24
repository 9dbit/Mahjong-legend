"""Mahjong Wild original sprite and sound asset renderer.

Use: python tools/build_assets.py
All exported gameplay sprites have alpha. The locked reference is flattened,
so layered sprites are newly reconstructed, not falsely claimed extracted originals.
"""
from __future__ import annotations
import json, math, random, subprocess, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'web'/'assets'
REFERENCE=Path('/mnt/data/a_highly_detailed_hdr_glossy_3d_neon_casino_slot.png')
REF_LOCAL=ROOT/'reference'/'locked_mahjong_wild_9x16.png'
if not REFERENCE.is_file() and REF_LOCAL.is_file(): REFERENCE=REF_LOCAL
if not REFERENCE.is_file() and (ASSETS/'reference'/'locked_style_reference.webp').is_file(): REFERENCE=(ASSETS/'reference'/'locked_style_reference.webp')
FNT_CJK='/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc'
FNT_LAT='/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'
if not Path(FNT_CJK).exists(): FNT_CJK=FNT_LAT
COLOR={'red':(160,27,20),'green':(11,103,67),'blue':(43,52,179),'gold':(236,161,37)}
MANIFEST={}

def directory(group): (ASSETS/group).mkdir(parents=True,exist_ok=True)
def write(group,name,im,role,more=None):
    directory(group)
    im=im.convert('RGBA')
    webp=ASSETS/group/(name+'.webp')
    im.save(webp,'WEBP',quality=85,method=2)
    MANIFEST[group+'/'+name]={'file':str(webp.relative_to(ROOT)).replace('\\','/'),'category':group,'role':role,'width':im.width,'height':im.height,'transparent':True,**(more or {})}
    return im

def gradient(w,h,top,bottom):
    ar=np.empty((h,w,4),dtype=np.uint8)
    for y in range(h):
        t=y/max(1,h-1); ar[y,:,0:3]=np.array(top)*(1-t)+np.array(bottom)*t;ar[y,:,3]=255
    return Image.fromarray(ar,'RGBA')

def glow(im, rad=10, opacity=0.8):
    a=im.getchannel('A').filter(ImageFilter.GaussianBlur(rad)).point(lambda x:int(x*opacity))
    out=Image.new('RGBA',im.size,(254,180,42,0));out.putalpha(a);out.alpha_composite(im);return out

def text_layer(s, color, w, h, sz, y=None,stroke=0,stroke_fill=(87,28,17), font=None):
    font=ImageFont.truetype(font or FNT_LAT,sz)
    im=Image.new('RGBA',(w,h)); d=ImageDraw.Draw(im)
    bb=d.textbbox((0,0),s,font=font,stroke_width=stroke)
    x=(w-(bb[2]-bb[0]))/2-bb[0]; y=(h-(bb[3]-bb[1]))/2-bb[1] if y is None else y
    d.text((x,y),s,font=font,fill=color,stroke_width=stroke,stroke_fill=stroke_fill)
    return im

def rounded_mask(sz,rect,radius):
    m=Image.new('L',sz,0);ImageDraw.Draw(m).rounded_rectangle(rect,radius=radius,fill=255);return m

def blank_tile(gold=False,w=164,h=184):
    bg=Image.new('RGBA',(w,h));shadow=Image.new('RGBA',(w,h))
    dd=ImageDraw.Draw(shadow)
    dd.rounded_rectangle((12,14,w-5,h-6),radius=19,fill=(18,9,4,170))
    bg.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5)))
    tile=gradient(w,h,(255,254,240) if not gold else (255,247,177),(224,218,196) if not gold else (219,109,13))
    mask=rounded_mask((w,h),(7,5,w-10,h-12),19)
    tile.putalpha(mask);bg.alpha_composite(tile)
    d=ImageDraw.Draw(bg)
    d.rounded_rectangle((7,5,w-10,h-12),radius=19,outline=(164,120,64,255),width=3)
    d.rounded_rectangle((12,11,w-16,h-20),radius=15,outline=(255,249,221,225),width=3)
    d.rounded_rectangle((15,14,w-20,h-24),radius=13,outline=(246,214,150,160) if gold else (195,190,166,90),width=2)
    d.line([(22,25),(w-34,25)],fill=(255,255,255,42),width=2)
    if gold:
        for i in range(11):
            x=random.Random(i+99).randint(28,w-23);y=random.Random(i+919).randint(26,h-30)
            d.ellipse((x-1,y-1,x+2,y+2),fill=(255,255,197,130))
    return bg

def dot_symbol(n):
    w=h=144;im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im)
    loc={2:[(47,43),(98,100)],3:[(42,34),(76,74),(107,114)],4:[(46,42),(99,42),(46,101),(99,101)],6:[(35,34),(73,34),(111,34),(35,100),(73,100),(111,100)]}[n]
    rr=16 if n in (2,3,4) else 14
    for k,(x,y) in enumerate(loc):
        c=[(36,72,177),(15,116,67),(193,35,27),(35,99,173),(8,105,75),(199,27,32)][k]
        d.ellipse((x-rr-1,y-rr+1,x+rr+1,y+rr+3),fill=(13,41,35,160))
        d.ellipse((x-rr,y-rr,x+rr,y+rr),fill=(233,234,205),outline=c,width=4)
        d.ellipse((x-rr+4,y-rr+4,x+rr-4,y+rr-4),fill=c)
        for j in range(5):
            a=2*math.pi*j/5;cx=x+6*math.cos(a);cy=y+6*math.sin(a)
            d.ellipse((cx-2,cy-2,cx+2,cy+2),fill=(239,236,172))
    return im

def bamboo_symbol(n):
    w=h=144;im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im)
    pts={2:[(52,52),(91,91)],3:[(38,38),(74,73),(109,108)],4:[(47,43),(95,43),(47,101),(95,101)],6:[(39,36),(71,36),(103,36),(39,102),(71,102),(103,102)]}[n]
    for k,(x,y) in enumerate(pts):
        c=(174,36,32) if k%3==1 else (0,107,56)
        d.rounded_rectangle((x-7,y-20,x+7,y+19),radius=5,fill=(8,49,28),outline=(230,224,164),width=1)
        d.rounded_rectangle((x-5,y-17,x+5,y+16),radius=3,fill=c)
        d.line((x,y-14,x,y+14),fill=(190,225,153),width=3)
        d.line((x-8,y-8,x+8,y-8),fill=(251,221,133),width=2)
        d.line((x-8,y+7,x+8,y+7),fill=(251,221,133),width=2)
        d.line((x-8,y-12,x-14,y-17),fill=c,width=3)
    return im

def character_symbol(ch, lower=None, col=(165,30,25)):
    im=Image.new('RGBA',(144,144));d=ImageDraw.Draw(im)
    font=ImageFont.truetype(FNT_CJK,83 if lower is None else 61)
    bb=d.textbbox((0,0),ch,font=font);w=bb[2]-bb[0]
    pos=(72-w/2-bb[0],31-bb[1] if lower else 42-bb[1])
    d.text((pos[0]+2,pos[1]+3),ch,font=font,fill=(52,34,15,108),stroke_width=1)
    d.text(pos,ch,font=font,fill=col,stroke_width=1,stroke_fill=(91,42,27))
    if lower:
        ft=ImageFont.truetype(FNT_CJK,55)
        bb=d.textbbox((0,0),lower,font=ft)
        pos2=(72-(bb[2]-bb[0])/2-bb[0],90-bb[1])
        d.text(pos2,lower,font=ft,fill=(160,36,30),stroke_width=1,stroke_fill=(91,42,27))
    return im

def wild_symbol():
    w=h=144;im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im)
    # A gold sycee ingot with a bright raised WILD crest.
    f=ImageFont.truetype(FNT_LAT,31)
    d.text((17,1),'WILD',font=f,fill=(255,245,163),stroke_width=2,stroke_fill=(150,55,3))
    d.ellipse((18,70,126,121),fill=(157,63,3),outline=(255,220,84),width=5)
    d.polygon([(13,73),(30,55),(45,61),(99,61),(112,54),(132,72),(115,120),(35,119)],fill=(224,130,2))
    d.ellipse((27,57,117,90),fill=(255,247,122),outline=(157,85,7),width=4)
    d.ellipse((42,63,103,82),fill=(174,79,4))
    d.arc((27,57,117,130),25,154,fill=(255,255,193),width=4)
    return glow(im,6,.6)

def scatter_symbol():
    im=Image.new('RGBA',(144,144));d=ImageDraw.Draw(im)
    d.rounded_rectangle((15,15,129,129),radius=20,fill=(164,23,20),outline=(248,186,49),width=7)
    layer=character_symbol('福',col=(246,213,87))
    layer=layer.resize((110,110),Image.Resampling.LANCZOS)
    im.alpha_composite(layer,(18,17));return im

def outlined_symbol_base(sym):
    if sym in 'ABCD':return dot_symbol({'A':2,'B':3,'C':4,'D':6}[sym])
    if sym in 'EFGH':return bamboo_symbol({'E':2,'F':3,'G':4,'H':6}[sym])
    if sym in 'IJKL':return character_symbol({'I':'一','J':'二','K':'五','L':'八'}[sym],'萬',(32,120,77) if sym in 'JL' else (157,40,35))
    if sym in 'MNO':return character_symbol({'M':'中','N':'發','O':'白'}[sym],None,{'M':(170,30,21),'N':(12,131,67),'O':(32,51,172)}[sym])
    if sym=='W':return wild_symbol()
    if sym=='S':return scatter_symbol()
    raise ValueError(sym)

def ornament_crop(image,box,color='gold'):
    im=image.crop(box).convert('RGBA'); a=np.array(im)
    rgb=a[:,:,:3].astype(np.float32); r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    gold=np.clip((g-r*.13-28)/78,0,1)*np.clip((r-b-35)/95,0,1)
    highlight=np.clip((r-75)/100,0,1)*np.clip((g-55)/115,0,1)
    # Retain golden sculpture highlights, fade dark background / screen red.
    alpha=(gold*.70+highlight*.40).clip(0,1)
    alpha=np.uint8((alpha**.7)*255)
    m=Image.fromarray(alpha,'L').filter(ImageFilter.GaussianBlur(1.1))
    im.putalpha(m)
    return im

def ornament_shapes(ref):
    # The left sculpture is reused with a perfect mirror, unlike the flattened reference.
    dragon=ornament_crop(ref,(0,92,249,345)).resize((348,357),Image.Resampling.LANCZOS)
    write('ornaments','dragon_left',dragon,'Header gold dragon, facing inward')
    write('ornaments','dragon_right',dragon.transpose(Image.Transpose.FLIP_LEFT_RIGHT),'Mirrored dragon: exact symmetry')
    lantern=ornament_crop(ref,(0,388,124,646)).resize((142,295),Image.Resampling.LANCZOS)
    write('ornaments','lantern_left',lantern,'Red 福 lantern ornament')
    write('ornaments','lantern_right',lantern.transpose(Image.Transpose.FLIP_LEFT_RIGHT),'Mirrored 福 lantern ornament')
    cloud=ornament_crop(ref,(0,985,189,1180)).resize((254,254),Image.Resampling.LANCZOS)
    write('ornaments','cloud_left',cloud,'Jade cloud detail')
    write('ornaments','cloud_right',cloud.transpose(Image.Transpose.FLIP_LEFT_RIGHT),'Mirrored jade cloud detail')


def panel(name,w,h,top,bottom,role,rounding=20):
    im=Image.new('RGBA',(w,h));s=Image.new('RGBA',(w,h));d=ImageDraw.Draw(s)
    d.rounded_rectangle((6,7,w-6,h-7),radius=rounding,fill=(14,8,6,175))
    im.alpha_composite(s.filter(ImageFilter.GaussianBlur(4)))
    ins=gradient(w,h,top,bottom);ins.putalpha(rounded_mask((w,h),(7,5,w-8,h-9),rounding));im.alpha_composite(ins)
    dd=ImageDraw.Draw(im)
    dd.rounded_rectangle((7,5,w-8,h-9),radius=rounding,outline=(239,168,37),width=5)
    dd.rounded_rectangle((13,10,w-14,h-16),radius=max(3,rounding-6),outline=(255,237,145),width=2)
    dd.line([(w*.20,12),(w*.65,12)],fill=(255,250,186,170),width=2)
    return write('ui',name,im,role)

def circle_button(name,label,sz=174,kind='jade'):
    im=Image.new('RGBA',(sz,sz));d=ImageDraw.Draw(im)
    d.ellipse((7,9,sz-8,sz-7),fill=(46,19,10,135))
    d.ellipse((9,5,sz-10,sz-15),fill=(133,74,12),outline=(251,202,53),width=8)
    d.ellipse((19,15,sz-20,sz-25),fill=(9,120,106) if kind=='jade' else (125,19,14),outline=(255,239,145),width=5)
    d.ellipse((27,22,sz-30,sz-35),outline=(56,235,187) if kind=='jade' else (247,153,42),width=4)
    tx=text_layer(label,(255,235,116),sz,sz,int(sz*.43),y=sz*.26,stroke=2)
    im.alpha_composite(tx)
    return write('ui',name,glow(im,5,.45),f'{name} interactive control')

def magic_effect(name,color,sz=228):
    im=Image.new('RGBA',(sz,sz))
    y,x=np.ogrid[:sz,:sz];r=np.sqrt((x-sz/2)**2+(y-sz/2)**2)/(sz/2)
    a=np.clip((1-r)*100,0,100).astype('uint8')
    px=np.zeros((sz,sz,4),dtype=np.uint8);px[:,:,:3]=color;px[:,:,3]=a
    im=Image.fromarray(px,'RGBA')
    d=ImageDraw.Draw(im)
    rd=random.Random(len(name))
    for i in range(22):
        x=rd.randrange(15,sz-15);y=rd.randrange(15,sz-15);k=rd.choice([2,3,4,5])
        d.line([(x-k,y),(x+k,y)],fill=(*color,230),width=2)
        d.line([(x,y-k),(x,y+k)],fill=(255,245,204,250),width=2)
    return write('effects',name,im,f'{name} transparent particles / animated overlay')

def generate_graphics():
    random.seed(20261024)
    for name,gold in [('base_ivory',False),('base_gold',True)]:write('tiles',name,blank_tile(gold),f'Blank {name} tile, alpha background')
    for sym in 'ABCDEFGHIJKLMNOWS':
        symbol=outlined_symbol_base(sym)
        write('symbols','symbol_'+sym,symbol,'Independent face artwork',{'engineSymbol':sym})
        tile=blank_tile(sym=='W')
        art=symbol.resize((133,133),Image.Resampling.LANCZOS)
        tile.alpha_composite(art,((tile.width-133)//2,21))
        write('tiles','tile_'+sym,tile,'Complete reusable Mahjong tile',{'engineSymbol':sym})
    img=Image.open(REFERENCE).convert('RGB') if REFERENCE.is_file() else None
    if img:
        ornament_shapes(img)
        (ASSETS/'reference').mkdir(exist_ok=True)
        img.resize((752,1338),Image.Resampling.LANCZOS).save(ASSETS/'reference'/'locked_style_reference.webp','WEBP',quality=75,method=2)
        MANIFEST['reference/locked_style_reference']={'file':'web/assets/reference/locked_style_reference.webp','role':'Locked composition reference only, not runtime sprite','transparent':False}
    panel('header',850,170,(163,35,24),(54,4,6),'Ornamental header bar',25)
    panel('multiplier',840,120,(0,163,137),(0,53,60),'Jade multiplier rail',38)
    panel('reel_backplate',838,1068,(55,12,9),(17,72,61),'Reel game board frame',24)
    panel('win_banner',835,138,(194,20,15),(87,4,13),'HDR win count ribbon',30)
    panel('meter',260,96,(10,85,73),(7,42,36),'Balance bet win value frame',14)
    panel('footer',830,108,(159,21,18),(93,11,14),'Control panel backdrop',28)
    circle_button('spin', '⟳',205,'jade')
    for name,label,kind in [('plus','+', 'jade'),('minus','−','jade'),('turbo','ϟ','gold'),('auto','▶','gold'),('menu','☰','gold'),('sound','♫','gold')]:
        circle_button(name,label,116,kind)
    title=Image.new('RGBA',(810,155));ts=text_layer('MAHJONG WILD',(255,221,103),810,155,72,stroke=5,stroke_fill=(105,27,7));title.alpha_composite(glow(ts,9,.9));write('ui','logo',title,'Mahjong Wild gold metal nameplate')
    for n,c in [('cascade_glow',(255,210,65)),('wild_transform',(250,177,12)),('reel_spark',(255,243,159)),('bonus_flare',(252,90,31)),('win_aura',(15,248,196)),('scatter_burst',(244,49,33))]:magic_effect(n,c)

def generate_audio():
    from scipy.signal import butter,sosfilt
    sr=22050; audio_path=ASSETS/'audio'; sfx=audio_path/'sfx';music=audio_path/'music'
    sfx.mkdir(parents=True,exist_ok=True);music.mkdir(parents=True,exist_ok=True)
    def save_wave(p,arr):
        arr=np.asarray(arr); arr=arr/(max(1,max(abs(arr)))*1.12)
        with wave.open(str(p),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes((arr*32767).astype('<i2').tobytes())
        MANIFEST[str(p.relative_to(ASSETS).with_suffix(''))]={'file':str(p.relative_to(ROOT)),'category':'audio','role':'Original synthesized game audio','sampleRate':sr}
    def cue(name,duration,start,end=None,type='sine',vol=.4):
        n=int(sr*duration);t=np.arange(n)/sr;end=end or start
        freq=start+(end-start)*np.minimum(1,t/duration)**.8
        ph=2*np.pi*np.cumsum(freq)/sr
        s=np.sin(ph)
        if type=='metal':s+=.32*np.sin(ph*2.011)+.17*np.sin(ph*3.991)
        if type=='noise':s=np.random.default_rng(17).normal(0,.8,size=n)*np.sin(ph*.25)
        attack=np.minimum(1,t/max(.005,duration*.06));decay=np.exp(-5.2*t/duration)
        save_wave(sfx/(name+'.wav'),s*attack*decay*vol)
    for args in [('spin',.44,700,155,'noise'),('reel_stop',.23,290,195,'metal'),('cascade',.4,520,830,'metal'),('tile_break',.21,510,155,'noise'),('wild',.72,390,1050,'metal'),('multiplier',.45,560,980,'metal'),('scatter',.7,670,1240,'metal'),('bonus',1.25,450,925,'metal'),('win',1.08,550,1300,'metal'),('button',.15,500,430,'sine')]: cue(*args)
    dur=12.0;t=np.arange(int(sr*dur))/sr;sc=np.array([0,3,7,10,12,15,19,22]);hz=110*2**(sc/12)
    base=np.zeros_like(t)
    for i in range(24):
        st=i*.5; note=hz[[0,2,4,6,4,2,1,3][i%8]]
        t0=t-st;env=np.maximum(0,np.minimum(1,t0/.15))*np.exp(-np.maximum(0,t0)*2.1)*(t0>=0)
        base+=.13*env*(np.sin(2*np.pi*note*t0)+.24*np.sin(2*np.pi*note*2.01*t0))
    drone=.025*(np.sin(2*np.pi*55*t)+.4*np.sin(2*np.pi*82.4*t))
    v=base+drone
    # Seamless at loop boundary via short overlap blending.
    n=int(sr*.20);v[-n:]=(np.linspace(1,0,n)*v[-n:]+np.linspace(0,1,n)*v[:n])
    tmp=music/'ambient_jade_loop.wav'; save_wave(tmp,v)
    ogg=music/'ambient_jade_loop.ogg'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(tmp),'-c:a','libvorbis','-q:a','3',str(ogg)],check=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(tmp),'-c:a','aac','-b:a','64k',str(music/'ambient_jade_loop.m4a')],check=True)
    MANIFEST['audio/music/ambient_jade_loop_aac']={'file':str((music/'ambient_jade_loop.m4a').relative_to(ROOT)),'category':'audio','role':'Safari-compatible AAC ambient music loop','durationSeconds':12}
    tmp.unlink()
    MANIFEST['audio/music/ambient_jade_loop']={'file':str(ogg.relative_to(ROOT)),'category':'audio','role':'Original ambient music loop; play after user interaction','durationSeconds':12}

def main():
    generate_graphics();generate_audio()
    out=ASSETS/'asset_manifest.json'
    out.write_text(json.dumps({'brand':'Mahjong Wild','styleLock':'9:16 HDR metallic gold + crimson enamel + jade neon; perfectly mirrored side ornaments','source':'Newly reconstructed sprites from flattened approved concept; no original editable PSD layers exist','assets':MANIFEST},ensure_ascii=False,indent=2)+'\n')
    print('Assets:',len(MANIFEST),'files; manifest:',out)
    for k in sorted(set(x['category'] for x in MANIFEST.values() if 'category' in x)):
        print(k,sum(1 for v in MANIFEST.values() if v.get('category')==k))
if __name__=='__main__':main()