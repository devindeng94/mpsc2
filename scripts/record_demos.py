"""Record four independent SC2 clients with a native game-window capture driver.

The default capture handshake expects CUA to save each requested window PNG.
The videos use a live overview plus observations from all four clients. SC2
renders the footage; titles, group labels and the scoreboard are added afterward.
RGB API capture is opt-in because Metal Base96883 returns blank RGB frames.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import imageio_ffmpeg
from loguru import logger
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from sc2.ids.ability_id import AbilityId
from s2clientprotocol import sc2api_pb2 as api, raw_pb2 as raw

from build_map import build, ROOT
from mpsc2.native_session import NativeFourSession

MODES = {
 'ffa': ('Four-player free-for-all', (0, 1, 2, 3), 'P1 vs P2 vs P3 vs P4'),
 '3v1': ('Three versus one', (0, 0, 0, 1), 'P1 + P2 + P3 vs P4'),
 '2v2': ('Two versus two', (0, 0, 1, 1), 'P1 + P2 vs P3 + P4'),
}
COLORS = ['#74c7ff','#ffb45d','#bc9bff','#83dfaa']
ARMY_SIZE = 12
FPS = 4  # four simulation loops per capture; playback is 0.71x Faster game speed
FONT = '/System/Library/Fonts/Supplemental/Arial.ttf'
BOLD = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'


def build_demo_map(mode, path):
 title, groups, label = MODES[mode]
 source = (ROOT/'maps/source/DemoArena.galaxy').read_text()
 source = source.replace('// GROUP_ASSIGNMENTS', '\n    '.join(
  f'if (p == {p}) {{ return {g+1}; }}' for p,g in enumerate(groups,1)))
 positions = [(48,48),(48,66),(80,48),(80,66)]
 if mode == '3v1':
  positions = [(48,45),(46,57),(48,69),(82,57)]
 source = source.replace('// ARMY_SPAWNS', '\n    '.join(
  f'armies[{p}] = UnitCreate({ARMY_SIZE}, "Marine", 0, {p}, Point({x}.0, {y}.0), {0 if x<64 else 180}.0);'
  for p,(x,y) in enumerate(positions,1)))
 return build(path, groups=groups, script=source.encode(), title='MPSC2 - '+title)


def inspect_alliances(observations, ids, groups):
 evidence=[]
 for response,pid in zip(observations,ids):
  obs=response.observation.observation
  assert obs.player_common.player_id==pid
  relations={}
  for u in obs.raw_data.units:
   if 1<=u.owner<=4:
    expected=raw.Self if u.owner==pid else raw.Ally if groups[u.owner-1]==groups[pid-1] else raw.Enemy
    assert u.alliance==expected,(pid,u.owner,u.alliance,expected)
    relations[u.owner]=raw.Alliance.Name(u.alliance)
  assert Counter(u.owner for u in obs.raw_data.units if 1<=u.owner<=4)=={p:ARMY_SIZE for p in range(1,5)}
  evidence.append({'player_id':pid,'observed_alliances':relations})
 return evidence


def engine_image(response):
 if isinstance(response, Image.Image):
  return response.copy()
 data=response.observation.observation.render_data.map
 if not data.data or data.bits_per_pixel!=24:
  raise RuntimeError('SC2 returned no 24-bit RGB image')
 image=Image.frombytes('RGB',(data.size.x,data.size.y),data.data)
 if max(np.asarray(image).std(axis=(0,1)))<1:
  raise RuntimeError('SC2 returned a blank RGB frame; no video will be published')
 return image


class Video:
 def __init__(self,path,mode,processes,ids):
  self.mode=mode; self.ids=ids; self.processes=processes
  self.fonts={s:ImageFont.truetype(FONT,s) for s in (16,18,20,22,24)}
  self.bold={s:ImageFont.truetype(BOLD,s) for s in (18,22,24,32,38)}
  self.writer=imageio_ffmpeg.write_frames(str(path),(1600,1000),fps=FPS,
   codec='libx264',pix_fmt_out='yuv420p',quality=8,macro_block_size=1,
   output_params=['-movflags','+faststart','-preset','fast'])
  self.writer.send(None); self.frames=0
 def frame(self,response,summary,stage='COMBAT',result=None):
  title,groups,label=MODES[self.mode]
  out=Image.new('RGB',(1600,1000),'#0b111c'); d=ImageDraw.Draw(out)
  d.text((30,22),'MPSC2  /  '+title,fill='white',font=self.bold[32])
  d.text((32,68),label,fill='#c1d4ea',font=self.fonts[22])
  d.text((1190,28),'4 INDEPENDENT CLIENTS',fill='#83dfaa',font=self.bold[22])
  # The native renderer's aspect ratio is retained, including its perspective.
  img=engine_image(response)
  img.thumbnail((1190,800),Image.Resampling.LANCZOS)
  px=24+(1190-img.width)//2; py=120+(800-img.height)//2
  out.paste(img,(px,py))
  d.rectangle((24,116,1214,920),outline='#354357',width=2)
  d.text((44,130),'SC2 GAME WINDOW  |  LIVE OVERVIEW',fill='#e0e9f5',font=self.bold[18])
  d.text((1240,125),stage,fill='#83dfaa',font=self.bold[24])
  d.text((1240,162),f"Game time  {summary['game_loop']/22.4:05.1f} s",fill='#afbed0',font=self.fonts[20])
  for p in range(1,5):
   y=225+(p-1)*144; g=groups[p-1]
   col=COLORS[g]
   d.rounded_rectangle((1238,y-12,1573,y+113),radius=12,fill='#152030')
   d.rectangle((1238,y,1243,y+90),fill=col)
   d.text((1258,y),f'PLAYER {p}  /  GROUP {g+1}',fill=col,font=self.bold[22])
   count=summary['alive'][p]
   d.text((1258,y+34),f'{count:02} / {ARMY_SIZE} Marines',fill='white',font=self.fonts[22])
   i=self.ids.index(p)
   status='Own policy / own units' if count else 'Army eliminated'
   if result: status=api.Result.Name(result[p]).upper()
   d.text((1258,y+70),status,fill='#acbed2',font=self.fonts[18])
  if result:
   winners=[p for p,r in result.items() if r==api.Victory]
   msg='WINNER: '+ ' + '.join(f'P{p}' for p in winners) if winners else 'DRAW'
   d.rounded_rectangle((300,795,940,885),radius=12,fill='#101c2b',outline='#83dfaa',width=2)
   d.text((330,818),msg,fill='white',font=self.bold[38])
  d.text((30,945),'Scripted combat demo  |  12 Marines per player  |  Full visibility  |  Slowed playback (0.71x)',
         fill='#afbed0',font=self.fonts[20])
  self.writer.send(np.asarray(out)); self.frames+=1
  return out
 def close(self):
  self.writer.close()


async def cameras(session):
 actions=[]
 for c in session.clients:
  a=api.Action()
  a.action_raw.camera_move.center_world_space.x=64
  a.action_raw.camera_move.center_world_space.y=51
  actions.append(c._execute(action=api.RequestAction(actions=[a])))
 await session.call(actions)


def summary(observations):
 obs=observations[0].observation.observation
 counts=Counter(u.owner for u in obs.raw_data.units if 1<=u.owner<=4)
 return {'game_loop':obs.game_loop,'alive':{p:counts[p] for p in range(1,5)}}


async def commands(session,observations,groups):
 tasks=[]; issuing=[]
 for c,r,pid in zip(session.clients,observations,session.player_ids):
  units=r.observation.observation.raw_data.units
  own=[u for u in units if u.owner==pid]
  enemy=[u for u in units if 1<=u.owner<=4 and groups[u.owner-1]!=groups[pid-1]]
  if not own or not enemy: continue
  x=sum(u.pos.x for u in own)/len(own); y=sum(u.pos.y for u in own)/len(own)
  target=min(enemy,key=lambda u:(u.pos.x-x)**2+(u.pos.y-y)**2)
  a=api.Action(); cmd=a.action_raw.unit_command
  cmd.ability_id=AbilityId.ATTACK_ATTACK.value
  cmd.unit_tags.extend(u.tag for u in own)
  cmd.target_unit_tag=target.tag
  tasks.append(c._execute(action=api.RequestAction(actions=[a])))
  issuing.append(pid)
 results=await session.call(tasks) if tasks else []
 return {pid:list(r.action.result) for pid,r in zip(issuing,results)}


async def record(args,mode):
 output=args.output/mode
 if output.exists(): raise FileExistsError(f'Use a fresh output directory: {output}')
 output.mkdir(parents=True)
 report={'status':'failed','mode':mode,'groups':MODES[mode][1],'source':'SC2 game window captured via CUA' if args.capture_dir else 'SC2 native RGB API','full_visibility':True}
 video=None
 try:
  map_path=build_demo_map(mode,output/f'{mode}.SC2Map')
  report['map_sha256']=hashlib.sha256(map_path.read_bytes()).hexdigest()
  async with NativeFourSession(map_path,output=output/'session',disable_fog=True,seed=7,
       render_size=None if args.capture_dir else (1280,800),window_size=(1280,800),
       graphics_api=args.graphics_api,timeout=90) as session:
   report['native_bridge']=session.native_metadata
   report['player_ids_in_client_order']=session.player_ids
   await session.step(8)
   await cameras(session)
   # Advance normally until camera transitions and render targets are ready.
   for _ in range(16):
    await session.step(1)
   observations=await session.observe()
   report['alliance_checks']=inspect_alliances(observations,session.player_ids,MODES[mode][1])
   host_i=session.player_ids.index(1)
   first_image=await capture(args,mode,0,summary(observations)) if args.capture_dir else observations[host_i]
   engine_image(first_image)
   report['source_frame_size']=list(engine_image(first_image).size)
   video=Video(output/f'{mode}.mp4',mode,session.native_metadata['processes'],session.player_ids)
   snap=summary(observations)
   report['timeline']=[snap]
   for _ in range(FPS*3):
    frame=video.frame(first_image,snap,'STARTING LINEUP')
   frame.save(output/'poster.jpg',quality=92)
   report['first_actions']=await commands(session,observations,MODES[mode][1])
   assert set(report['first_actions'])=={1,2,3,4}
   assert all(v==[1] for v in report['first_actions'].values())
   last_response=first_image
   for step in range(4*120):
    if all(r.observation.player_result for r in observations): break
    if not any(r.observation.player_result for r in observations):
     assert len({r.observation.observation.game_loop for r in observations})==1
    if step%2==0:
     await commands(session,observations,MODES[mode][1])
    await session.step(4)
    observations=await session.observe()
    snap=summary(observations)
    # The terminal API sometimes omits RGB; retain the final combat image then.
    if not observations[host_i].observation.player_result:
     last_response=await capture(args,mode,step+1,snap) if args.capture_dir else observations[host_i]
    frame=video.frame(last_response,snap)
    if step%20==0:
     print(f'{mode}: loop {snap["game_loop"]}, armies {snap["alive"]}',flush=True)
     report['timeline'].append(snap)
    if step==30: frame.save(output/'combat.jpg',quality=92)
   results=[{p.player_id:p.result for p in r.observation.player_result} for r in observations]
   assert all(len(r)==4 and r==results[0] for r in results),results
   result=results[0]; winners=[p for p,r in result.items() if r==api.Victory]
   assert winners,'Demo ended in a draw'
   winner_group=MODES[mode][1][winners[0]-1]
   assert set(winners)=={p for p in range(1,5) if MODES[mode][1][p-1]==winner_group}
   for _ in range(FPS*4):
    frame=video.frame(last_response,snap,'MATCH COMPLETE',result)
   frame.save(output/'result.jpg',quality=92)
   report['terminal_results_by_client']=results
   report['terminal_game_loops']=[r.observation.observation.game_loop for r in observations]
   await session.save_replay(output/f'{mode}.SC2Replay')
   report['video_frames']=video.frames; report['fps']=FPS
   report['duration_seconds']=video.frames/FPS
   report['status']='passed'
   if args.capture_dir: (args.capture_dir/'complete.json').write_text(json.dumps({'mode':mode,'status':'passed'}))
 finally:
  if video: video.close()
  (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
 print(f'Completed {mode}: {output / (mode+".mp4")}',flush=True)


async def capture(args,mode,index,snap):
 directory=args.capture_dir
 directory.mkdir(parents=True,exist_ok=True)
 key=f'{mode}-{index:05}'
 target=directory/(key+'.png')
 request={'mode':mode,'index':index,'path':str(target.resolve()),'summary':snap}
 tmp=directory/'request.tmp'
 tmp.write_text(json.dumps(request))
 tmp.replace(directory/'request.json')
 deadline=asyncio.get_running_loop().time()+300
 while not target.exists():
  if asyncio.get_running_loop().time()>deadline: raise TimeoutError('Waiting for CUA frame '+key)
  await asyncio.sleep(.03)
 # Capture only the application window; remove its macOS title bar.
 image=Image.open(target).convert('RGB')
 image=image.crop((0,56,image.width,image.height))
 return image


async def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--mode',choices=[*MODES,'all'],default='all')
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--graphics-api',default=None)
 parser.add_argument('--capture-dir',type=Path,help='Directory for CUA screenshot/step handshake')
 parser.add_argument('--rgb',action='store_true',help='Use the RGB API on compatible renderers (not Metal Base96883)')
 args=parser.parse_args()
 if not args.rgb and args.capture_dir is None: args.capture_dir=args.output/"capture"
 logger.remove(); logger.add(sys.stderr,level='WARNING')
 for mode in MODES if args.mode=='all' else [args.mode]:
  await record(args,mode)

if __name__=='__main__':
 asyncio.run(main())
