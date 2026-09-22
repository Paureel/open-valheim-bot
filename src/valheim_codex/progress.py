"""Small, explicit short-term feedback, derived only from the player's observations."""
from collections import deque


class Progress:
    def __init__(self):
        self.recent = deque(maxlen=6)
        self.supplies = None
        self.unchanged = 0

    def context(self, context):
        status = context["status"]
        supplies = sorted((i["name"], i["count"]) for i in status.get("supplies", []))
        if self.supplies == supplies:
            self.unchanged += 1
        else:
            self.unchanged = 0
        self.supplies = supplies
        context["progress"] = {"recent_actions": list(self.recent),
            "observations_without_supply_change": self.unchanged,
            "guidance": ("Keep one attainable survival objective until completed or blocked. "
                "For food/wood, use visible pickups or a small reachable sapling; ignore Hugin unless you need his advice. "
                "A blocked move requires a different route. Failed interaction requires aiming or moving closer, not another blind interact. "
                "Supplies must actually increase before reporting a pickup. Several consecutive punches may be needed for one small sapling.")}
        # Persistent history remains on disk; only the relevant recent dialogue needs
        # to be repeated alongside every new image in the model context.
        context["conversation"] = context.get("conversation", [])[-10:]
        context["memories"] = context.get("memories", [])[:10]
        return context

    def record(self, decision, result):
        self.recent.append({"action": decision.get("action"), "note": decision["note"], "result": result})
