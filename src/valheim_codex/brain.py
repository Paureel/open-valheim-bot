"""Small, read-only activity feed. Never contains credentials or model reasoning."""
import json
import time
import uuid
from collections import deque
from .config import private_write


class BrainFeed:
    def __init__(self, config, shadow=False):
        self.path = config.home / "run/brain.json"
        self.events = deque(maxlen=48)
        self.sequence = 0
        self.state = {"run": uuid.uuid4().hex, "phase": "warming", "shadow": shadow,
                      "thinking": False, "intent": "", "objective": "", "speech": "",
                      "moving": False, "body_at": 0, "talk_until": 0,
                      "perception_ms": None, "planning_ms": None, "frame_age_ms": None}
        self.publish()

    def publish(self, **updates):
        self.state.update(updates)
        try:
            private_write(self.path, json.dumps(dict(self.state, updated_at=time.time(),
                sequence=self.sequence, events=list(self.events)), ensure_ascii=False))
        except OSError:
            # An observation tool must never interfere with the player controls.
            pass

    def fire(self, system, regions, detail="", **updates):
        self.sequence += 1
        self.events.append({"id": self.sequence, "at": time.time(), "system": system,
                            "regions": list(dict.fromkeys(regions)), "detail": str(detail)[:200]})
        self.publish(**updates)

    def perception(self, milliseconds, age, reason):
        self.fire(1, ["see"], reason, perception_ms=round(milliseconds), frame_age_ms=round(age))

    def motor(self, controls, reason):
        regions = []
        if controls.get("yaw_rate") or controls.get("pitch_rate"):
            regions.append("look")
        if controls.get("block"):
            regions.append("block")
        button = {"jump": "jump", "interact": "interact", "primary_attack": "attack"}.get(controls.get("button"))
        if button:
            regions.append(button)
        if regions or not (controls.get("forward") or controls.get("strafe")):
            self.fire(1, regions or ["stop"], reason)

    def body(self, status):
        moving = status.get("locomotion", {}).get("speed_mps", 0) > .2
        if moving and not self.state["moving"]:
            self.fire(1, ["move"], "Moving", moving=True, body_at=time.time())
        else:
            self.publish(moving=moving, body_at=time.time())

    def plan(self, plan, milliseconds):
        intent = plan.get("intent")
        updates = {"thinking": False, "planning_ms": round(milliseconds)}
        regions = ["plan"]
        if intent:
            mode = intent["mode"]
            regions.append({"travel":"explore", "inspect":"explore", "gather":"gather",
                "harvest":"gather", "combat":"combat", "craft":"craft", "organize":"inventory", "rest":"rest"}[mode])
            updates.update(intent=mode, objective=str(intent["objective"])[:240])
        self.fire(2, regions, updates.get("objective", "Plan ready"), **updates)

    def speech(self, text):
        self.fire(2, ["talk"], text, speech=str(text)[:160], talk_until=time.time()+max(2,min(6,len(text)/18)))


def read_feed(path, now=None):
    """A crashed/disconnected producer must not leave a live or thinking display."""
    now = time.time() if now is None else now
    empty = {"phase":"offline", "thinking":False, "events":[], "sequence":0, "run":None}
    try:
        if path.stat().st_size > 128 * 1024:
            return empty
        state = json.loads(path.read_text())
        if not isinstance(state, dict) or not isinstance(state.get("updated_at"), (int, float)):
            return empty
        if now - state["updated_at"] > 4 and state.get("phase") not in ("stopped", "failed"):
            state.update(phase="offline", thinking=False)
        return state
    except (OSError, ValueError, TypeError):
        return empty
