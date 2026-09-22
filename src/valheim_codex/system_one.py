"""Isolated, warm local classifier. One request in flight; never a frame backlog."""
import base64
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from .config import ROOT

HYPOTHESES = [
    "The person can walk forward without hitting anything.",
    "There is open unobstructed ground to the left of the person.",
    "There is open unobstructed ground to the right of the person.",
    "The person is standing behind a fallen log.",
    "There is water or a steep drop immediately in front of the person.",
    "There is an obstacle immediately in front of the person.",
]


class Worker:
    def __init__(self, config):
        python = ROOT / ".tools/system-one/bin/python"
        if not python.exists():
            raise RuntimeError("Run scripts/setup-system-one.py with native Python 3.12 first")
        self.log = open(config.home / "logs/system-one.log", "a")
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), TOKENIZERS_PARALLELISM="false",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        self.process = subprocess.Popen([str(python), "-m", "valheim_codex.system_one", "--worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1, cwd=ROOT, env=env)
        self.inbox = queue.Queue(maxsize=2)
        self.busy = False
        self.sent_at = 0
        threading.Thread(target=self._read, daemon=True).start()
        try:
            ready = self.inbox.get(timeout=60)
            if not ready or ready.get("type") != "ready":
                raise RuntimeError("System 1 startup failed; see logs/system-one.log")
            self.identity = ready
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 100000:
                    break
                self.inbox.put(json.loads(line), timeout=1)
        except (ValueError, queue.Full):
            pass
        finally:
            try:
                self.inbox.put(None, timeout=1)
            except queue.Full:
                pass

    def submit(self, request):
        if self.busy:
            return False
        self.busy, self.sent_at = True, time.monotonic()
        self.process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
        self.process.stdin.flush()
        return True

    def poll(self):
        try:
            result = self.inbox.get_nowait()
        except queue.Empty:
            if self.busy and time.monotonic() - self.sent_at > 3:
                raise TimeoutError("Local vision worker stalled; controls expire independently")
            return None
        self.busy = False
        if result is None or "error" in result:
            raise RuntimeError("Local vision worker failed; see logs/system-one.log")
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()
        self.log.close()


def candidates(target=""):
    if not target:
        return HYPOTHESES
    return HYPOTHESES + ["The " + target + " is visible on the " + where + " of the image."
                         for where in ("left", "center", "right")]


def score_frame(model, png, target=""):
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(png, validate=True))).convert("RGB")
    width, height = image.size
    # Ground-level central view keeps small nearby barriers at useful resolution.
    # This crop is deterministic and uses pixels only, never scene metadata.
    image = image.crop((int(width*.18), int(height*.32), int(width*.85), int(height*.96)))
    return model.score("The image shows a third-person video game.", candidates(target), image)


def worker_main():
    from .openjev import OpenJev
    from PIL import Image
    profile=os.environ.get("VALHEIM_SYSTEM_ONE_IMAGE_PROFILE","standard")
    if profile not in ("standard","compact"):
        raise ValueError("Unknown local image profile")
    model = OpenJev(ROOT / ".tools/models/openjev-0.8b", quantize_bits=8,
        image_size=(256,144) if profile=="compact" else (384,216),
        min_pixels=32768 if profile=="compact" else 65536)
    # Compile/cache Metal kernels before the motor can be resumed.
    model.score("A video game.", HYPOTHESES, Image.new("RGB", (384, 216)))
    # Do not retain gigabytes of unused conversion/prefill buffers beside the
    # game renderer in this machine's unified memory.
    model.mx.set_cache_limit(512*1024*1024)
    model.mx.clear_cache()
    print(json.dumps({"type": "ready", "identity": model.identity}), flush=True)
    for line in sys.stdin:
        if len(line) > 8_000_000:
            raise ValueError("Oversize worker request")
        request = json.loads(line)
        try:
            target = request.get("target", "")
            if not isinstance(target, str) or len(target) > 80:
                raise ValueError("Invalid target")
            result = score_frame(model, request["png"], target)
            result.update({k: request[k] for k in ("frame_id", "captured_at", "revision", "epoch")})
            print(json.dumps(result, allow_nan=False), flush=True)
        except Exception as exc:
            print(json.dumps({"error": type(exc).__name__}), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Private worker entrypoint only")
    worker_main()
