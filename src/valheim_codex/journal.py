"""Private, bounded-run evidence: no credentials or raw model protocol."""
import base64
import json
import os
import time
from .config import private_write


class PlayJournal:
    def __init__(self, config):
        self.path = config.home / "playtests" / (time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns()))
        self.path.mkdir(parents=True, mode=0o700)
        private_write(self.path / "run.json", json.dumps({"model": config.settings["model"],
            "reasoning_effort": config.settings["reasoning_effort"], "world_id": config.settings["world_id"],
            "started_at": time.time(), "state": "running"}))
        self.started = time.monotonic()
        self.count = 0

    def observation(self, status, image):
        self.count += 1
        prefix = f"{self.count:04d}"
        images = [c for c in image["content"] if c.get("type") == "image" and c.get("mimeType") == "image/png"]
        if len(images) != 1:
            raise ValueError("One observation image required for journal")
        with os.fdopen(os.open(str(self.path / (prefix + ".png")), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(base64.b64decode(images[0]["data"], validate=True))
        private_write(self.path / (prefix + "-status.json"), json.dumps(status, ensure_ascii=False))

    def decision(self, decision):
        private_write(self.path / f"{self.count:04d}-decision.json", json.dumps(decision, ensure_ascii=False))

    def result(self, result, seconds, usage=None):
        private_write(self.path / f"{self.count:04d}-result.json", json.dumps({"decision_seconds": seconds,
            "model_usage": usage or {}, "result": result}, ensure_ascii=False))

    def finish(self, error=None):
        private_write(self.path / "summary.json", json.dumps({"observations": self.count,
            "elapsed_seconds": round(time.monotonic() - self.started, 2), "error": error,
            "state": "failed" if error else "stopped"}))
