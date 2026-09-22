#!/usr/bin/env python3
"""Reproducible native runtime/checkpoint setup. Run with arm64 Python 3.12."""
import hashlib
import json
import platform
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from valheim_codex.openjev import REPOSITORY, REVISION, SUBFOLDER

WEIGHT_SHA256 = "cf6d62a341c0c804f9a926eec71aefc9859adb28978736e757b49bce35d9b8f8"
FILES = ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
         "preprocessor_config.json", "chat_template.jinja", "video_preprocessor_config.json", "train_result.json"]


def main():
    if platform.system() != "Darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Use native arm64 Python 3.12 on this Mac; do not use Rosetta Python.")
    venv = ROOT / ".tools/system-one"
    if not (venv / "bin/python").exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run([str(venv / "bin/python"), "-m", "pip", "install", "-r", str(ROOT / "requirements-system-one.txt")], check=True)
    folder = ROOT / ".tools/models/openjev-0.8b"
    folder.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = folder / name
        if not path.exists():
            print("Downloading pinned " + name, flush=True)
            url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{SUBFOLDER}/{name}"
            temporary = path.with_suffix(path.suffix + ".partial")
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                while data := response.read(1024*1024):
                    output.write(data)
            temporary.replace(path)
    digest = hashlib.sha256()
    with (folder / "model.safetensors").open("rb") as source:
        while data := source.read(1024*1024):
            digest.update(data)
    if digest.hexdigest() != WEIGHT_SHA256:
        raise SystemExit("Model weight hash mismatch; checkpoint refused")
    (folder / "provenance.json").write_text(json.dumps({"repo":REPOSITORY,"revision":REVISION,"subfolder":SUBFOLDER}))
    print("Installed exact trained OpenJev 0.8B; weight SHA256 verified.")


if __name__ == "__main__":
    main()
