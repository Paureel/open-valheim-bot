#!/usr/bin/env python3
"""Record normal gameplay + matching brain telemetry from an operator-reviewed plan.

This is explicitly a guided demonstration, not an autonomous-model evaluation.
Only the game's own camera is recorded; the desktop and credentials are excluded.
"""
import argparse
import base64
import fcntl
import json
import signal
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from valheim_codex.awake import Awake
from valheim_codex.brain import BrainFeed
from valheim_codex.config import Config, private_write
from valheim_codex.dual_supervisor import snapshot
from valheim_codex.motor import controls
from valheim_codex.protocol import LocalClient, unpack
from valheim_codex.supervisor import wait_for_focus


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text())
    for step in plan:
        if set(step)-{"at","duration","forward","yaw_rate","button","speech","tool","label"}:
            raise ValueError("Unknown guided step field")
        if not 0<=step["at"]<60 or not 0<=step.get("duration",0)<=4:
            raise ValueError("Each guided motion must be <=4 seconds within a 60-second recording")
        if not -1<=step.get("forward",0)<=1 or not -70<=step.get("yaw_rate",0)<=70:
            raise ValueError("Guided movement out of bounds")
        if step.get("button","none") not in ("none","jump") or step.get("tool") not in (None,"open_inventory","close_inventory"):
            raise ValueError("This recorder only supports movement, a jump, speech, and own inventory")
    config=Config();client=LocalClient(config);stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set());signal.signal(signal.SIGTERM,lambda *_:stop.set())
    args.output.mkdir(parents=True,exist_ok=False)
    frames=args.output/"frames";frames.mkdir()
    request=config.home/"run/view-recording-until"
    lock=open(config.home/"run/supervisor.lock","a+")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    awake=Awake();brain=None;failure=None
    manifest={"mode":"guided","duration":60,"frames":[],"started_at":None,"completed":False}
    try:
        wait_for_focus(client,stop)
        client.request("/control/stop",{})
        context=client.request("/context",{})
        if not context["bridge"].get("ready"):raise RuntimeError("Game not ready")
        initial=snapshot(client);health=initial["status"]["health"]
        client.request("/control/resume",{})
        context=client.request("/context",{});epoch=context["epoch"]
        private_write(request,str(int(time.time()+65)))
        brain=BrainFeed(config);brain.publish(phase="guided",objective="Looking around")
        start=time.monotonic();wall=time.time();manifest["started_at"]=wall
        seen=set();last_frame=None;last_motor=-10;next_status=0;current=initial["status"]
        print("Recording 60 seconds of guided gameplay: "+str(args.output),flush=True)
        with open(args.output/"brain.jsonl","w") as timeline:
            while not stop.is_set() and time.monotonic()-start<60:
                now=time.monotonic();elapsed=now-start
                if now>=next_status:
                    h=client.call("health")
                    if h["paused"] or h["bridge"].get("paused") or not h["bridge"].get("ready"):
                        raise RuntimeError("Operator/game pause during recording")
                    current=client.call("get_status");brain.body(current);next_status=now+.1
                    if current["health"]<health or current.get("swimming") or current.get("dead"):
                        raise RuntimeError("Character safety stop during recording")
                began=time.time()
                image=client.call("observe_player_view")
                view=next(json.loads(c["text"]) for c in image["content"] if c.get("type")=="text")
                frame=view["frame_id"]
                if frame!=last_frame:
                    name=f"{len(manifest['frames']):05d}.png"
                    png=next(c["data"] for c in image["content"] if c.get("type")=="image")
                    (frames/name).write_bytes(base64.b64decode(png,validate=True))
                    manifest["frames"].append({"file":name,"at":max(0,began-view["age_ms"]/1000-wall)})
                    last_frame=frame
                active=None
                for i,step in enumerate(plan):
                    if elapsed>=step["at"] and i not in seen:
                        seen.add(i)
                        if step.get("speech"):
                            result=client.call("send_chat",{"text":step["speech"],"type":"normal"})
                            if not unpack(result).get("ok"):raise RuntimeError("Chat was not delivered")
                            brain.speech(step["speech"])
                        if step.get("tool"):
                            result=client.call(step["tool"],{})
                            if not unpack(result).get("ok"):raise RuntimeError("Inventory operation rejected")
                            brain.fire(2,["inventory"],step["tool"])
                            last_motor=now+.5
                        brain.publish(objective=step.get("label","Observing"))
                    if step["at"]<=elapsed<step["at"]+step.get("duration",0):active=step
                if now-last_motor>=.25 and not current.get("inventory",{}).get("open"):
                    command=controls(frame,forward=(active or {}).get("forward",0),yaw_rate=(active or {}).get("yaw_rate",0))
                    if active and active.get("button") and elapsed-active["at"]<.3:command["button"]=active["button"]
                    result=unpack(client.request("/control/motor",{"epoch":epoch,"arguments":command}))
                    if not result.get("ok"):raise RuntimeError(result.get("error","Motor rejected"))
                    brain.motor(command,(active or {}).get("label","Resting"));last_motor=now
                timeline.write(json.dumps(dict(brain.state,at=time.time()-wall,events=list(brain.events)))+"\n")
                stop.wait(.03)
        manifest["completed"]=not stop.is_set() and time.monotonic()-start>=60
        manifest["elapsed_seconds"]=round(time.monotonic()-start,3)
    except BaseException as exc:
        failure=type(exc).__name__+": "+str(exc)
        raise
    finally:
        try:client.request("/control/stop",{})
        finally:
            if brain:brain.publish(phase="stopped",moving=False,thinking=False)
            request.unlink(missing_ok=True);awake.close();lock.close()
            manifest["error"]=failure
            (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    print("Recorded "+str(len(manifest["frames"]))+" actual camera frames; controls released.",flush=True)


if __name__=="__main__":main()
