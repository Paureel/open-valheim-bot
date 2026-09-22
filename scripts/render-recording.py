#!/usr/bin/env python3
"""Compose real camera frames and timestamp-matched brain activity into 60s MP4."""
import argparse
import bisect
import io
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
import resvg_py

ROOT=Path(__file__).resolve().parents[1]
BG="#10151b";INK="#e8edf2";MUTED="#8e9caa";ONE="#75e1d3";TWO="#baa6fa"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads((args.recording/"manifest.json").read_text())
    if not manifest.get("completed") or manifest["elapsed_seconds"]<60:
        raise ValueError("Refusing to present an incomplete capture as a one-minute recording")
    frames=manifest["frames"]
    if not frames:raise ValueError("No real camera frames")
    states=[json.loads(line) for line in (args.recording/"brain.jsonl").read_text().splitlines()]
    frame_times=[f["at"] for f in frames];state_times=[s["at"] for s in states]
    markup=(ROOT/"web/brain/index.html").read_text()
    svg=re.search(r'<svg id="brain".*?</svg>',markup,re.S).group()
    svg=svg.replace('<svg id="brain"','<svg xmlns="http://www.w3.org/2000/svg" id="brain"')
    style='''svg{font-family:Helvetica,sans-serif}.outline{stroke:#34424d;stroke-width:1.6}.one .outline{fill:url(#left-tint)}.two .outline{fill:url(#right-tint)}.one .region path{fill:#75e1d3}.two .region path{fill:#baa6fa}.region path{fill-opacity:.025;stroke:#34424d;stroke-width:1}.region text{fill:#9aa9b7;font-size:21px;text-anchor:middle;dominant-baseline:middle}.region.active path{fill-opacity:.42;stroke-width:2}.one .region.active path{stroke:#75e1d3}.two .region.active path{stroke:#baa6fa}.region.active text{fill:#ffffff;font-weight:bold}.folds{fill:none;stroke:#34424d;stroke-width:1.3;stroke-linecap:round;opacity:.65}#bridge-path{fill:none;stroke:#34424d;stroke-width:1}'''
    svg=svg.replace('<defs>','<style>'+style+'</style><defs>')
    font_path='/System/Library/Fonts/Helvetica.ttc'
    fonts={size:ImageFont.truetype(font_path,size) for size in (16,18,21,24,26,30,34)}
    base=Image.new('RGB',(1920,1080),BG)
    d=ImageDraw.Draw(base)
    d.text((40,50),'Valheim',font=fonts[30],fill=INK)
    d.text((1230,50),'brain',font=fonts[30],fill=INK)
    d.text((1868,56),'Guided demonstration',font=fonts[18],fill=MUTED,anchor='ra')
    d.line((1200,130,1200,962),fill='#25303a',width=1)
    d.text((1286,233),'SYSTEM 1',font=fonts[16],fill=MUTED)
    d.text((1830,233),'SYSTEM 2',font=fonts[16],fill=MUTED,anchor='ra')
    d.text((1286,262),'OpenJev',font=fonts[26],fill=INK)
    d.text((1830,262),'Luna',font=fonts[26],fill=INK,anchor='ra')
    d.text((1286,299),'Local controls',font=fonts[16],fill=MUTED)
    d.text((1830,299),'Intentions & speech',font=fonts[16],fill=MUTED,anchor='ra')
    cache={};last_file=None;game=None;report={'duration_seconds':60,'output_fps':30,'source_frames':len(frames),'mode':'guided','moving_seconds':0,'talking_seconds':0}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    process=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080','-r','30','-i','-',
        '-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)],stdin=subprocess.PIPE,stderr=open(args.recording/'encode.log','w'))
    try:
        for n in range(1800):
            t=n/30;absolute=manifest['started_at']+t
            state=states[max(0,bisect.bisect_right(state_times,t)-1)]
            frame=frames[max(0,bisect.bisect_right(frame_times,t)-1)]
            if frame['file']!=last_file:
                game=Image.open(args.recording/'frames'/frame['file']).convert('RGB').resize((1152,648),Image.Resampling.LANCZOS)
                last_file=frame['file']
            active=set()
            for event in state.get('events',[]):
                if 0<=absolute-event['at']<.7:active.update(event['regions'])
            # Move is actual body motion, never merely an accepted input.
            active.discard('move')
            if state.get('moving') and 0<=absolute-state.get('body_at',0)<.75:active.add('move');report['moving_seconds']+=1/30
            if absolute<state.get('talk_until',0):active.add('talk');report['talking_seconds']+=1/30
            key=tuple(sorted(active))
            if key not in cache:
                current=svg
                for name in active:current=current.replace(f'class="region" data-region="{name}"',f'class="region active" data-region="{name}"')
                cache[key]=Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=current,width=680,height=461))).convert('RGBA')
            picture=base.copy();picture.paste(game,(24,250));picture.paste(cache[key],(1220,330),cache[key])
            draw=ImageDraw.Draw(picture)
            draw.text((40,930),f'{int(t):02d} / 60',font=fonts[18],fill=MUTED)
            speech=state.get('speech','') if absolute<state.get('talk_until',0)+2 else ''
            if speech:
                for i,line in enumerate(textwrap.wrap('“'+speech+'”',78)):
                    draw.text((60,147+i*34),line,font=fonts[26],fill=INK)
            for i,line in enumerate(textwrap.wrap(state.get('objective',''),46)):
                draw.text((1560,830+i*28),line,font=fonts[21],fill=INK,anchor='ma')
            process.stdin.write(picture.tobytes())
            if n in (210,690,1410):picture.save(args.recording/f'preview-{n//30}.jpg',quality=90)
        process.stdin.close()
        if process.wait()!=0:raise RuntimeError('Video encoder failed; see encode.log')
    finally:
        if process.poll() is None:process.kill();process.wait()
    report={k:round(v,2) if isinstance(v,float) else v for k,v in report.items()}
    (args.recording/'video-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report));print(args.output)


if __name__=='__main__':main()
