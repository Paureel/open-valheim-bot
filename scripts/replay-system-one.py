#!/usr/bin/env python3
"""Replay labelled local camera frames, without starting or controlling Valheim.

PYTHONPATH=src .tools/system-one/bin/python scripts/replay-system-one.py manifest.json output.json
Manifest: [{"image":"/absolute/frame.png", "allow_forward":false, "label":"log"}]
"""
import base64
import json
import statistics
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from valheim_codex.openjev import OpenJev
from valheim_codex.system_one import score_frame
from valheim_codex.motor import Motor
from valheim_codex.intents import Intent


def main():
    cases=json.loads(Path(sys.argv[1]).read_text())
    model=OpenJev(ROOT/".tools/models/openjev-0.8b",quantize_bits=8)
    report=[]
    for case in cases:
        png=base64.b64encode(Path(case["image"]).read_bytes()).decode()
        motor=Motor()
        intent=Intent(1,"replay","replay",0,100,0,0,{"mode":"travel","target":""})
        for frame in range(1,4):
            result=score_frame(model,png)
            result["frame_id"]=frame
            controls,reason=motor.choose(intent,result,{"stamina":50},frame*.5)
        forward=controls["forward"]>0 and controls["button"]=="none"
        report.append({**case,"support":result["support"],"seconds":result["seconds"],
                       "controls":controls,"reason":reason,"false_clear":forward and not case["allow_forward"]})
    output={"model":model.identity,"cases":report,"median_ms":statistics.median(x["seconds"] for x in report)*1000,
            "false_clear":sum(x["false_clear"] for x in report)}
    Path(sys.argv[2]).write_text(json.dumps(output,indent=2))
    print(json.dumps(output,indent=2))
    if output["false_clear"]:
        raise SystemExit("Critical replay gate failed")


if __name__=="__main__":main()
