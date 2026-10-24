import subprocess,time,urllib.request,urllib.error
from pathlib import Path
p=Path(__file__).resolve().parents[1]
pr=subprocess.Popen(['python','-m','mahjong_legend','--port','8895'],cwd=p,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(80):
  try:urllib.request.urlopen('http://127.0.0.1:8895/',timeout=1);break
  except:time.sleep(.1)
 items=[('/','text/html'),('/assets/mahjong-wild.css','text/css'),('/assets/tiles/tile_M.webp','image/webp'),('/assets/ornaments/dragon_right.webp','image/webp'),('/assets/audio/player.js','application/javascript'),('/assets/audio/music/ambient_jade_loop.m4a','audio/mp4'),('/assets/audio/sfx/wild.wav','audio/x-wav')]
 for path,mime in items:
  with urllib.request.urlopen('http://127.0.0.1:8895'+path,timeout=3) as r:
   t=r.headers.get_content_type();print(path,r.status,t,len(r.read()));assert r.status==200 and (t==mime or ('wav' in t and 'wav' in mime))
 try:urllib.request.urlopen('http://127.0.0.1:8895/assets/../mahjong_legend/math_config.json',timeout=3);raise AssertionError('Traversal allowed')
 except urllib.error.HTTPError as e:assert e.code==404
finally:pr.terminate();pr.wait(timeout=5)