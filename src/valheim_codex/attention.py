"""A small working view; full evidence and long-term memory remain on disk."""
import json
from .policy import DECISION_SCHEMA, object_schema, tool_choice


def plain_result(value):
    if isinstance(value, dict):
        if "content" in value:
            texts = [c.get("text", "") for c in value["content"] if c.get("type") == "text"]
            try:
                return plain_result(json.loads(texts[0])) if len(texts) == 1 else texts
            except (ValueError, TypeError):
                return texts
        return {k: plain_result(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [plain_result(v) for v in value]
    return value


def working_context(context):
    """Omit transport metadata and repeated tool envelopes, never trust labels."""
    status = dict(context.get("status", {}))
    for key in ("world_id", "character_name", "vision_source", "frame_age_ms", "remote_chat_identity"):
        status.pop(key, None)
    recent = context.get("progress", {}).get("recent_actions", [])[-4:]
    recent = [{"action": r.get("action"), "why": r.get("note"), "result": plain_result(r.get("result"))} for r in recent]
    return {"status": status, "view": context.get("view"), "social": context.get("social"),
        "combat_enabled": context.get("settings", {}).get("combat_enabled", False),
        "goals": context.get("goals", []), "memories": context.get("memories", [])[:5],
        "conversation": context.get("conversation", [])[-6:],
        "recent": recent, "last_result": plain_result(context.get("last_action_result")),
        "pacing": context.get("pacing", {})}


def decision_schema(context):
    """Only offer controls appropriate to the currently observed UI."""
    status = context.get("status", {})
    if status.get("map", {}).get("open"):
        names = ["close_map", "map_zoom", "stop"]
    elif status.get("inventory", {}).get("open"):
        names = ["close_inventory", "inventory_move", "inventory_use", "select_recipe", "craft_selected", "cancel_crafting", "stop"]
    else:
        names = ["stride", "approach_interact", "halt", "look", "aim_at", "move", "interact", "jump", "open_inventory", "open_map", "use_hotbar", "stop"]
        if context.get("settings", {}).get("combat_enabled"):
            names += ["primary_attack", "secondary_attack", "block"]
    props = dict(DECISION_SCHEMA["properties"])
    props["note"] = {"type": "string", "maxLength": 140}
    props["action"] = {"anyOf": [{"type": "null"}] + [tool_choice(n) for n in names]}
    return object_schema(props)
