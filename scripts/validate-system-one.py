#!/usr/bin/env python3
"""Compare native/shared-prefix NLI against the trained PyTorch reference.

Run with .tools/system-one/bin/python. Optional PNG arguments add real frame
checks; they are read locally and never sent to a remote model.
"""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    parser.add_argument("--dtype",choices=("float32","float16","bfloat16"),default="float16")
    parser.add_argument("--bits",type=int,choices=(0,4,8),default=8,help="Language weight bits; 0 keeps full weights")
    parser.add_argument("--profile",choices=("standard","compact"),default="standard")
    parser.add_argument("images",nargs="*")
    args=parser.parse_args()
    import numpy as np
    import torch
    from PIL import Image
    from transformers import AutoModelForSequenceClassification
    from valheim_codex.openjev import OpenJev
    from valheim_codex.system_one import HYPOTHESES
    path=ROOT/".tools/models/openjev-0.8b"
    native=OpenJev(path,compute_dtype=args.dtype,quantize_bits=args.bits or None,
        image_size=(256,144) if args.profile=="compact" else (384,216),
        min_pixels=32768 if args.profile=="compact" else 65536)
    reference=AutoModelForSequenceClassification.from_pretrained(path,local_files_only=True,
        trust_remote_code=False,dtype=torch.float32).eval()
    torch.set_num_threads(4)
    cases=[("A person holds a red apple.",["The apple is red.","The apple is blue.","The person is in Paris."],None)]
    for color in ("red","blue"):
        cases.append(("An image of a solid color.",["The picture is red.","The picture is blue.","The picture is green."],Image.new("RGB",(384,216),color)))
    for file in args.images:
        image=Image.open(file).convert("RGB")
        cases.append(("The image shows a third-person video game.",HYPOTHESES,image))
        w,h=image.size
        cases.append(("The image shows a third-person video game.",HYPOTHESES,
            image.crop((int(w*.18),int(h*.32),int(w*.85),int(h*.96)))))
    report=[]
    for premise,hypotheses,image in cases:
        prepared=native.prepare(premise,hypotheses,image)
        inputs={"input_ids":torch.tensor(prepared["numpy_ids"]),"attention_mask":torch.tensor(prepared["numpy_mask"])}
        if prepared["visual"]:
            pixels,grid=prepared["visual"]
            inputs.update(pixel_values=torch.from_numpy(np.array(pixels)).repeat(len(hypotheses),1),
                image_grid_thw=torch.from_numpy(np.array(grid)).repeat(len(hypotheses),1),
                mm_token_type_ids=(inputs["input_ids"]==248056).long())
        with torch.inference_mode():
            expected=torch.softmax(reference(**inputs).logits.float(),-1).numpy()
        plain=native.score(premise,hypotheses,image,share_prefix=False)
        shared=native.score(premise,hypotheses,image,share_prefix=True)
        warm=native.score(premise,hypotheses,image,share_prefix=True)
        delta=float(np.abs(np.array(shared["nli"])-expected).max())
        prefix_delta=float(np.abs(np.array(shared["nli"])-np.array(plain["nli"])).max())
        # Stable candidate ordering as well as small numeric error.
        passed=delta<.03 and prefix_delta<.03 and shared["choice"]==int(expected[:,1].argmax())
        report.append({"hypotheses":hypotheses,"reference":expected.tolist(),"native":shared["nli"],
            "max_difference":delta,"prefix_difference":prefix_delta,"seconds":warm["seconds"],"pass":passed})
        print(json.dumps({k:v for k,v in report[-1].items() if k not in ("reference","native")}),flush=True)
    Path(args.output).write_text(json.dumps({"model":native.identity,"cases":report},indent=2))
    if not all(row["pass"] for row in report):
        raise SystemExit("Native inference parity failed")


if __name__=="__main__":main()
