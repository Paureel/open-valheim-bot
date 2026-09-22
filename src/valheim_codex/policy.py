import re
import time
from collections import deque
from difflib import SequenceMatcher
from .protocol import TOOL_MAP, MEMORY_TOOLS, validate


def object_schema(props, required=None):
    return {"type": "object", "properties": props, "required": list(props) if required is None else required, "additionalProperties": False}


def tool_choice(name):
    schema = TOOL_MAP[name]["inputSchema"]
    # Structured outputs use all-required properties: defaults are supplied by the model.
    schema = dict(schema, required=list(schema["properties"]))
    return object_schema({"tool": {"type": "string", "enum": [name]}, "arguments": schema})


ACTION_NAMES = ["stride", "approach_interact", "travel_to", "halt", "open_map", "close_map", "map_zoom", "aim_at", "look", "move", "jump", "crouch", "interact", "primary_attack", "secondary_attack", "block", "use_hotbar", "stop", "open_inventory", "close_inventory", "inventory_move", "inventory_use", "select_recipe", "craft_selected", "cancel_crafting"]
WRITE_NAMES = ["remember_fact", "remember_location", "update_goal"]
DECISION_SCHEMA = object_schema({
    "note": {"type": "string", "maxLength": 500},
    "action": {"anyOf": [{"type": "null"}] + [tool_choice(n) for n in ACTION_NAMES]},
    "source_event_id": {"anyOf": [{"type": "null"}, {"type": "integer", "minimum": 1, "maximum": 9007199254740991}]},
    "speech": {"anyOf": [{"type": "null"}, object_schema({"text": {"type": "string", "minLength": 1, "maxLength": 160},
        "type": {"type": "string", "enum": ["normal", "shout"]}, "voluntary": {"type": "boolean"}})]},
    "memories": {"type": "array", "maxItems": 3, "items": {"anyOf": [tool_choice(n) for n in WRITE_NAMES]}},
})


class SpeechGate:
    def __init__(self, settings, clock=time.monotonic):
        self.settings, self.clock = settings, clock
        self.last = -float("inf")
        self.recent = deque(maxlen=12)

    def check(self, text, voluntary=False):
        if not self.settings["chat_enabled"] or (voluntary and not self.settings["voluntary_chat_enabled"]):
            raise ValueError("Chat disabled")
        if not text.strip() or text.lstrip().startswith("/") or any(ord(c) < 32 for c in text):
            raise ValueError("Invalid chat text")
        # Valheim/Unity strings use UTF-16 code units; installed UI limit is 127.
        if len(text.encode("utf-16-le")) // 2 > self.settings["maximum_message_length"]:
            raise ValueError("Chat too long")
        normalized = re.sub(r"\W+", "", text.casefold())
        if self.clock() - self.last < self.settings["min_seconds_between_messages"]:
            raise ValueError("Chat cooldown")
        if any(SequenceMatcher(None, old, normalized).ratio() >= 0.85 for old in self.recent):
            raise ValueError("Near-duplicate chat")
        return normalized

    def sent(self, normalized):
        self.last = self.clock()
        self.recent.append(normalized)


def validate_decision(decision, config, conversation, session_id):
    validate(decision, DECISION_SCHEMA)
    source = decision["source_event_id"]
    if source is not None:
        event = next((e for e in reversed(conversation) if e["event_id"] == source and e.get("session_id") == session_id), None)
        if event is None:
            raise ValueError("Request event is not in the recent conversation")
        if config.settings["trusted_players_only_for_gameplay_requests"] and not config.is_trusted(event):
            if decision["action"] or any(m["tool"] == "update_goal" for m in decision["memories"]):
                raise ValueError("Untrusted player cannot provide gameplay instructions")
    action = decision["action"]
    if action and not config.settings["combat_enabled"] and action["tool"] in ("primary_attack", "secondary_attack", "block"):
        raise ValueError("Combat is disabled")
    if action and action["arguments"].get("duration_ms", 0) > config.settings["max_action_ms"]:
        raise ValueError("Action duration exceeds maximum")
