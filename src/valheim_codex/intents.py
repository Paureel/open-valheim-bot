"""Bounded planner intentions and stale-result arbitration; no game I/O."""
import math
from dataclasses import dataclass
from .policy import DECISION_SCHEMA, object_schema
from .protocol import validate

INTENT_SCHEMA = object_schema({
    "mode": {"type": "string", "enum": ["travel", "inspect", "gather", "harvest", "combat", "craft", "organize", "rest"]},
    "objective": {"type": "string", "minLength": 1, "maxLength": 180},
    "target": {"type": "string", "maxLength": 80},
    "heading": {"type": "number", "minimum": -120, "maximum": 120},
    "distance": {"type": "number", "minimum": 0, "maximum": 20},
    "seconds": {"type": "integer", "minimum": 3, "maximum": 30},
    "recipe_id": {"type": "string", "maxLength": 128},
    "inventory_action": {"anyOf": [{"type": "null"}] +
        [v for v in DECISION_SCHEMA["properties"]["action"]["anyOf"]
         if v.get("properties", {}).get("tool", {}).get("enum", [None])[0] in ("inventory_use", "inventory_move", "close_inventory")]},
})
PLAN_SCHEMA = object_schema({"intent": {"anyOf":[{"type":"null"},INTENT_SCHEMA]}, **{
    k: v for k, v in DECISION_SCHEMA["properties"].items() if k != "action"}})


def validate_plan(plan, config, context):
    validate(plan, PLAN_SCHEMA)
    source = plan["source_event_id"]
    if source is not None:
        event = next((e for e in context["conversation"] if e["event_id"] == source and
                      e.get("session_id") == context["session_id"]), None)
        if event is None or (plan["intent"] is not None and config.settings["trusted_players_only_for_gameplay_requests"] and not config.is_trusted(event)):
            raise ValueError("An untrusted or expired chat request cannot create an intention")
    intent = plan["intent"]
    if intent is None:
        return
    if intent["mode"] == "combat" and not config.settings["combat_enabled"]:
        raise ValueError("Combat disabled")
    if intent["mode"] in ("gather", "harvest", "combat") and not intent["target"].strip():
        raise ValueError("This skill requires a named visible target")


def angle(value):
    return (value + 180) % 360 - 180


@dataclass
class Intent:
    revision: int
    epoch: str
    session: str
    issued: float
    expires: float
    heading: float
    start_distance: float
    data: dict

    @classmethod
    def create(cls, plan, revision, context, now):
        data = dict(plan["intent"])
        # The heading belongs to the actual planner image, not to the later view
        # that happens to be current when the cloud response arrives.
        yaw = context["view"]["camera_yaw"]
        return cls(revision, context["epoch"], context["session_id"], now, now + data["seconds"],
                   angle(yaw + data["heading"]), context["status"].get("locomotion", {}).get("distance_m", 0), data)

    def accepts(self, result, now, epoch, session):
        return (epoch == self.epoch and session == self.session and
                result.get("revision") == self.revision and result.get("epoch") == self.epoch and
                self.issued <= result.get("captured_at", -math.inf) <= now < self.expires and
                0 <= now - result.get("captured_at", -math.inf) <= .85)

    def complete(self, status, now):
        if now >= self.expires:
            return "rest complete" if self.data["mode"] == "rest" else "intention time budget exhausted"
        if self.data["mode"] == "travel" and status.get("locomotion", {}).get("distance_m", 0) - self.start_distance >= self.data["distance"]:
            return "travel distance budget reached; inspect destination"
        return None
