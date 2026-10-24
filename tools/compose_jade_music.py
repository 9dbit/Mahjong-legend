"""Original soft pentatonic loop. Developer tool requires numpy and ffmpeg.
Encoded outputs are committed; no runtime dependency or external recording.
"""
from pathlib import Path
import numpy as np
import subprocess, wave, json, hashlib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/approved-v082/audio';OUT.mkdir(parents=True,exist_ok=True)
SR=44100; BPM=76; beat=60/BPM; seconds=64*beat; N=round(seconds*SR)
a=np.zeros((N,2),dtype=np.float64); rng=np.random.default_rng(20261024)
def note(midi):return 440*2**((midi-69)/12)
def put(tone,position,amp,pan=0):
    start=round(position*SR); idx=(start+np.arange(len(tone)))%N
    a[idx,0]+=tone*amp*np.sqrt((1-pan)/2);a[idx,1]+=tone*amp*np.sqrt((1+pan)/2)
def pluck(midi,dur=3):
    t=np.arange(round(dur*SR))/SR;f=note(midi);x=np.zeros_like(t)
    for k in range(1,9):x+=np.sin(2*np.pi*f*k*t+(.04*k))*np.exp(-t*(1.6+.62*k))/(k**1.2)
    return x*(1-np.exp(-t*240))
def flute(midi,dur):
    t=np.arange(round(dur*SR))/SR;f=note(midi);phase=2*np.pi*f*t+.035*np.sin(2*np.pi*4.7*t)
    env=np.minimum(t/.19,1)*np.minimum((dur-t)/.38,1);env=np.clip(env,0,1)
    breath=rng.normal(0,1,len(t));breath=np.convolve(breath,np.ones(17)/17,mode='same')
    return (np.sin(phase)+.13*np.sin(phase*2)+.045*np.sin(phase*3)+.012*breath)*env*.66
chords=[[50,57,62,66],[47,54,59,62],[43,50,55,59],[45,52,57,62]]
for bar in range(16):
    chord=chords[(bar//2)%4]
    for j,m in enumerate(chord):put(pluck(m), (bar*4+j*.8)*beat,.115,-.35+j*.21)
    if bar%2==1:put(pluck(chord[2]+12,2.2),(bar*4+3.2)*beat,.055,.45)
melody=[(0,74,2),(3,78,1.6),(6,81,2.4),(10,78,2),(13,76,2),(17,74,3),(22,71,2),(26,69,3),(32,74,2),(35,76,2),(39,78,2.2),(43,81,2.5),(48,78,2),(51,76,2),(55,74,3),(60,69,2.3)]
for pos,m,d in melody:put(flute(m,d*beat),pos*beat,.12,.12)
# Quiet drone and spaced bell overtones. Seam is circular, not a hard file fade.
t=np.arange(N)/SR
for m in [38,45]:
    f=note(m);cycles=round(f*seconds);drone=np.sin(2*np.pi*cycles*np.arange(N)/N)
    a[:,0]+=drone*.013;a[:,1]+=drone*.013
for bar in [0,4,8,12]:put(pluck(86,5),(bar*4+.15)*beat,.045,-.4)
dry=a.copy()
for delay,gain in [(.131,.18),(.237,.13),(.371,.09),(.613,.055)]:a+=np.roll(dry,round(delay*SR),axis=0)*gain
peak=float(np.max(np.abs(a)));a*=.62/max(peak,.001)
raw=OUT/'jade_serenity.wav'
with wave.open(str(raw),'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR);w.writeframes(np.clip(a*32767,-32767,32767).astype('<i2').tobytes())
for ext,args in [('m4a',['-c:a','aac','-b:a','128k','-movflags','+faststart']),('ogg',['-c:a','libvorbis','-q:a','4'])]:
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(raw),*args,str(OUT/f'jade_serenity.{ext}')],check=True)
raw.unlink()
(OUT/'music.json').write_text(json.dumps({'title':'Jade Serenity','composer':'Mahjong Wild original procedural composition','bpm':BPM,'seconds':seconds,'style':'soft pentatonic plucked strings, flute-like melody and light bells','source':'tools/compose_jade_music.py','files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in OUT.glob('*') if f.suffix in ['.m4a','.ogg']}},indent=2)+'\n')
print('Original music rendered',seconds,'seconds', 'RMS',round(float(np.sqrt(np.mean(a*a))),4))
