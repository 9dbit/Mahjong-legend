#!/usr/bin/env python3
"""Original gentle oriental score and ceramic SFX. Python standard library only."""
from array import array
from pathlib import Path
import hashlib,json,math,random,sys,wave
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/audio/oriental-v082'
SR=22050
TAU=2*math.pi

def freq(note):return 440*2**((note-69)/12)
def blank(seconds):return array('f',[0.0])*round(seconds*SR)
def add(dst,src,at=0,gain=1,circular=False):
    start=round(at*SR)
    for i,value in enumerate(src):
        j=start+i
        if circular:dst[j%len(dst)]+=value*gain
        elif 0<=j<len(dst):dst[j]+=value*gain

def pluck(note,seconds=1.7,gain=1):
    f=freq(note);out=blank(seconds)
    for i in range(len(out)):
        t=i/SR
        body=(math.sin(TAU*f*t)*math.exp(-t*2.2)+.38*math.sin(TAU*f*2.002*t)*math.exp(-t*3.8)+.17*math.sin(TAU*f*3.006*t)*math.exp(-t*5.1)+.06*math.sin(TAU*f*4.012*t)*math.exp(-t*7.5))
        out[i]=body*min(1,t/.004)*min(1,(seconds-t)/.05)*gain
    return out

def flute(note,seconds,gain=1):
    f=freq(note);rng=random.Random(note*17+round(seconds*100));out=blank(seconds);phase=0;breath=0
    for i in range(len(out)):
        t=i/SR;phase+=TAU*f/SR*(1+.0023*math.sin(TAU*4.8*t));breath=breath*.91+rng.uniform(-1,1)*.09
        env=min(1,t/.10)*min(1,(seconds-t)/.22)
        out[i]=(math.sin(phase)+.16*math.sin(phase*2)+.035*math.sin(phase*3)+breath*.07)*env*gain
    return out

def ceramic(seconds=.3,seed=1,gain=1):
    rng=random.Random(seed);out=blank(seconds);noise=0
    modes=[(740,.52,24),(1417,.31,35),(2341,.18,48),(3180,.07,65)]
    for i in range(len(out)):
        t=i/SR;noise=.65*noise+.35*rng.uniform(-1,1)
        body=sum(a*math.sin(TAU*f*t)*math.exp(-t*d) for f,a,d in modes)
        out[i]=(body*.52+noise*.22*math.exp(-t*90))*min(1,t/.0015)*gain
    return out

def bell(note,seconds=.75,gain=.18):
    f=freq(note);out=blank(seconds)
    for i in range(len(out)):
        t=i/SR
        out[i]=gain*min(1,t/.006)*min(1,(seconds-t)/.04)*(math.sin(TAU*f*t)*math.exp(-t*5)+.14*math.sin(TAU*f*2.76*t)*math.exp(-t*9))
    return out

def reverb(samples,circular=False):
    dry=array('f',samples)
    for delay,gain in ((.113,.17),(.241,.105),(.389,.065)):add(samples,dry,delay,gain,circular)

def save(name,samples,target=.79):
    if name not in ('jade_garden_loop','reel_roll'):
        # Reverberation tails end smoothly instead of being abruptly truncated.
        fade=min(round(.025*SR),len(samples))
        for i in range(fade):samples[-fade+i]*=(fade-1-i)/max(1,fade-1)
    peak=max(abs(v) for v in samples) or 1;gain=min(1.35,target/peak)
    pcm=array('h',(round(max(-.96,min(.96,v*gain))*32767) for v in samples))
    if sys.byteorder!='little':pcm.byteswap()
    path=OUT/(name+'.wav')
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(SR);f.writeframes(pcm.tobytes())
    rms=math.sqrt(sum((v*gain)**2 for v in samples)/len(samples))
    return {'file':str(path.relative_to(ROOT/'web')),'duration':round(len(samples)/SR,4),'peak':round(min(peak*gain,.96),5),'rms':round(rms,5),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def music():
    beat=60/68;out=blank(32*beat)
    chords=[(50,57,62,66),(47,54,59,62),(43,50,55,59),(45,52,57,64),(50,57,62,66),(47,54,59,62),(43,50,55,59),(45,52,57,62)]
    for bar,chord in enumerate(chords):
        for off,n,level in ((0,chord[0],.15),(1.1,chord[2],.095),(2.05,chord[1],.10),(3.35,chord[3],.085)):
            add(out,pluck(n,2.4,level),(bar*4+off)*beat,circular=True)
    melody=[(0,74,1.4),(1.5,78,1.1),(3,81,1.6),(4.8,78,1.2),(6.2,76,1.4),(8,74,1.2),(9.5,71,1.4),(11.3,69,1.6),(13.3,71,1.5),(15.3,76,1.5),(17,78,1.2),(18.5,81,1.5),(20.5,83,1.3),(22,81,1.5),(24.1,78,1.4),(26,76,1.2),(27.5,74,2.4)]
    for ix,(when,note,length) in enumerate(melody):
        add(out,pluck(note,2.5,.14 if ix%4 else .17),when*beat,circular=True)
        if ix in (2,6,10,14,16):add(out,flute(note-12,length*beat,.048),(when+.16)*beat,circular=True)
    for when,note in ((7.6,86),(15.6,81),(23.6,86),(31.2,81)):add(out,bell(note,1.5,.022),when*beat,circular=True)
    for when in (0,8,16,24):add(out,ceramic(.16,round(when)+31,.026),when*beat,circular=True)
    reverb(out,True)
    return out

def effects():
    out={'button':ceramic(.14,7,.48),'reel_stop':ceramic(.23,11,.76),'crack':blank(.23),'tile_break':blank(.85),'spin':blank(.42),'reel_roll':blank(1.5)}
    for at,g in ((0,.52),(.055,.25),(.112,.18)):add(out['crack'],ceramic(.115,round(at*100)+20,g),at)
    add(out['tile_break'],ceramic(.30,45,.90))
    for i in range(7):add(out['tile_break'],ceramic(.20,80+i,.26*math.exp(-i*.20)),.08+i*.061)
    for i,n in enumerate((86,90,93)):add(out['tile_break'],bell(n,.43,.09),.07+i*.08)
    for i in range(6):add(out['spin'],ceramic(.10,100+i,.13+i*.016),.015+i*.045)
    rng=random.Random(831);low=0
    for i in range(len(out['reel_roll'])):
        t=i/SR;low=.89*low+.11*rng.uniform(-1,1);out['reel_roll'][i]=low*.09*(.5+.5*math.sin(TAU*8*t)**2)
    for name,notes,spacing,g in [('cascade',(74,78,81),.073,.22),('wild',(74,81,86),.13,.24),('multiplier',(78,81,86),.10,.25),('scatter',(81,86),.13,.20),('win',(74,78,81,86),.12,.25),('bonus',(74,78,81,86,90),.18,.25),('bigwin',(62,74,78,81,86,90),.18,.25)]:
        out[name]=blank(len(notes)*spacing+.78)
        for i,n in enumerate(notes):add(out[name],pluck(n,.80,g),i*spacing)
        reverb(out[name])
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    entries={'jade_garden_loop':save('jade_garden_loop',music(),.72)}
    entries.update({name:save(name,samples) for name,samples in effects().items()})
    manifest={'version':'0.8.2','original':True,'sampleRate':SR,'channels':1,'music':{'title':'Jade Garden','bpm':68,'bars':8,'mood':'Gentle original oriental instrumental','instruments':['soft synthesized zither','flute-like breath tone','sparse bells','soft wood accents']},'assets':entries}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'audio_assets':len(entries),'music_seconds':entries['jade_garden_loop']['duration'],'total_bytes':sum(e['bytes'] for e in entries.values())}))
if __name__=='__main__':main()
