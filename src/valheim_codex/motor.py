"""Deterministic arbitration of local visual evidence and a bounded intention."""
import re
from .intents import angle


def controls(frame_id, **updates):
    value = {"frame_id": frame_id, "forward": 0, "strafe": 0, "yaw_rate": 0, "pitch_rate": 0,
             "sprint": False, "block": False, "button": "none", "duration_ms": 800}
    value.update(updates)
    return value


class Motor:
    def __init__(self):
        self.clear_streak = 0
        self.blocked_since = None
        self.last_jump = -100
        self.last_attack = -100
        self.last_interact = -100
        self.last_frame = -1
        self.revision = None
        self.last_direction = 0
        self.direction_until = 0
        self.previous_intent = None
        self.last_evidence_at = -100
        self.detour_heading = None
        self.detour_until = 0
        self.detour_start = 0
        self.scans = 0
        self.scan_direction = 0

    def choose(self, intent, evidence, status, now):
        frame = evidence["frame_id"]
        if self.revision != intent.revision:
            previous = self.previous_intent
            continuing = previous and previous.data["mode"] == intent.data["mode"] == "travel" and (
                previous.epoch == intent.epoch and previous.session == intent.session and
                now < previous.expires and now-self.last_evidence_at <= .85 and
                abs(angle(previous.heading-intent.heading)) <= 25)
            streak, last_frame, blocked = self.clear_streak, self.last_frame, self.blocked_since
            self.__init__()
            self.revision = intent.revision
            self.previous_intent = intent
            if continuing:
                # A same-corridor extension need not insert a forced idle frame.
                # This call still requires a new image and current clear evidence.
                self.clear_streak, self.last_frame, self.blocked_since = streak, last_frame, blocked
        if frame <= self.last_frame:
            return None, "duplicate frame"
        self.last_frame = frame
        self.last_evidence_at = now
        result = controls(frame)
        mode = intent.data["mode"]
        if mode in ("rest", "craft", "organize"):
            return result, mode
        if status.get("swimming") or status.get("encumbered") or status.get("dead"):
            return result, "own status prevents travel"
        if status.get("damage_reflex", {}).get("blocking"):
            return result, "damage; reassess"
        locomotion = status.get("locomotion", {})
        if self.detour_heading is not None and (now>=self.detour_until or
                locomotion.get("distance_m",0)-self.detour_start>=3):
            self.detour_heading = None
        destination = intent.heading if self.detour_heading is None else self.detour_heading
        heading = angle(destination - locomotion.get("camera_yaw", intent.heading))
        if mode == "inspect" or abs(heading) > 35:
            result["yaw_rate"] = max(-100, min(100, heading * 3)) if abs(heading) > 2 else 0
            return result, "inspect" if mode == "inspect" else "turn toward intention"
        scores = evidence["support"]
        if len(scores) < 6 or any(not 0 <= s <= 1 for s in scores):
            return result, "invalid local evidence"
        forward, left, right, log, danger, obstacle = scores[:6]
        # These are uncalibrated NLI scores, not independent safety probabilities.
        # Peripheral stones/logs can support both descriptions. Require a strong
        # forward claim AND a margin over the barrier claim; a confident nearby
        # log still stops travel unless the barrier claim is very weak.
        clear = (forward >= .72 and obstacle < .6 and forward-obstacle >= .3 and
                 (log < .75 or obstacle < .2))
        if not clear and abs(heading)>8:
            # The requested corridor may be beside the obstructed current view.
            # Turn to inspect it before declaring that intention impassable.
            result["yaw_rate"] = max(-75,min(75,heading*2))
            return result,"turn toward intention"
        if danger >= .35:
            self.clear_streak = 0
            return result, "possible water or drop; reassess"
        target = intent.data["target"]
        if mode in ("gather", "harvest", "combat"):
            if len(scores) != 9 or max(scores[6:]) < .72:
                return result, "target lost; reassess"
            where = max(range(3), key=lambda i: scores[6+i])
            if scores[6+where] - sorted(scores[6:])[-2] < .12:
                return result, "target location uncertain; reassess"
            if where != 1:
                result["yaw_rate"] = -28 if where == 0 else 28
                return result, "center target"
            caption = status.get("hover_text", "").splitlines()
            caption = caption[0].casefold() if caption else ""
            if re.search(r"(?<!\w)"+re.escape(target.casefold())+r"(?!\w)",caption):
                if mode == "gather" and now - self.last_interact > 1.5:
                    result["button"] = "interact"
                    self.last_interact = now
                    return result, "interact; verify inventory"
                if mode in ("combat", "harvest") and now - self.last_attack > 1.1 and status.get("stamina", 0) > 15:
                    result["button"] = "primary_attack"
                    self.last_attack = now
                    return result, "swing; verify outcome"
        self.clear_streak = self.clear_streak + 1 if clear else 0
        if clear and self.clear_streak >= 2:
            result.update(forward=1, yaw_rate=max(-45, min(45, heading*2)))
            return result, "clear travel"
        if log >= .75 and obstacle >= .3 and now - self.last_jump >= 3 and status.get("stamina", 0) >= 20:
            # An actual visual log claim is required; collision alone never jumps.
            result.update(forward=.7, button="jump")
            self.last_jump = now
            return result, "observed low log; jump once"
        if max(left, right) >= .85 and abs(left-right) >= .2 and (obstacle >= .4 or log >= .6):
            direction = -1 if left > right else 1
            if now < self.direction_until and self.last_direction != direction:
                return result, "detour unstable; reassess"
            self.last_direction, self.direction_until = direction, now+1
            self.detour_heading=angle(locomotion.get("camera_yaw",intent.heading)+direction*30)
            self.detour_until=now+4
            self.detour_start=locomotion.get("distance_m",0)
            result["yaw_rate"] = direction*38
            return result, "look toward visible detour"
        if not clear and mode=="travel":
            if self.detour_heading is not None:
                return result,"inspect local detour"
            if self.scans<2:
                direction=(-1 if left>=right else 1) if self.scans==0 else -self.scan_direction
                self.scans+=1;self.scan_direction=direction
                self.detour_heading=angle(intent.heading+direction*30)
                self.detour_until=now+4
                self.detour_start=locomotion.get("distance_m",0)
                turn=angle(self.detour_heading-locomotion.get("camera_yaw",intent.heading))
                result['yaw_rate']=max(-60,min(60,turn*2))
                return result,"inspect local detour"
        return result, "checking clear path" if clear else "uncertain path; reassess"
