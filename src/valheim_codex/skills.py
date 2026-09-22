"""Small normal-UI sequences. Acknowledgements never count as completed work."""


class InventorySkill:
    def __init__(self, intent):
        self.intent = intent
        self.stage = "open"
        self.before = None
        self.result = None
        self.output_name = None
        self.destination_before = None

    def step(self, status):
        """Return (tool operation, outcome). One operation per fresh status."""
        inv = status.get("inventory", {})
        mode = self.intent.data["mode"]
        recipe_id = self.intent.data["recipe_id"]
        operation = self.intent.data["inventory_action"]
        def action(tool, arguments=None):
            return {"tool": tool, "arguments": arguments or {}}, None
        if self.stage == "closing":
            if inv.get("open"):
                return None, None
            self.stage = "done"
            return None, self.result
        if self.stage == "done":
            return None, self.result
        if mode == "organize" and operation and operation["tool"] == "close_inventory":
            if not inv.get("open"):
                return None, "inventory closed"
            self.stage, self.result = "closing", "inventory closed"
            return action("close_inventory")
        if not inv.get("open"):
            if self.stage == "opening":
                return None,None
            if self.stage != "open":
                return None, "inventory unexpectedly closed"
            self.stage = "opening"
            return action("open_inventory")
        if inv.get("loading"):
            return None, None
        if self.stage in ("open", "opening"):
            self.stage = "ready"
        if mode == "organize" and operation is None:
            return None, "inventory inspected; choose observed item or recipe"
        if mode == "craft":
            recipe = next((r for r in inv.get("recipes", []) if r["recipe_id"] == recipe_id), None)
            if not recipe:
                return None, "selected recipe is not known"
            if self.stage == "ready":
                if not recipe.get("requirements_met"):
                    return None, "recipe lacks materials or station"
                self.stage = "selected"
                return action("select_recipe", {"recipe_id": recipe_id})
            if self.stage == "selected":
                if inv.get("selected_recipe_id") != recipe_id or not inv.get("can_craft"):
                    return None, "recipe selection/craft availability changed"
                self.output_name = recipe["name"]
                self.before = sum(i["count"] for i in status.get("supplies", []) if i["name"] == self.output_name)
                self.stage = "crafting"
                return action("craft_selected", {"recipe_id": recipe_id})
            if self.stage == "crafting":
                if inv.get("crafting"):
                    return None, None
                last = inv.get("last_craft") or {}
                count = sum(i["count"] for i in status.get("supplies", []) if i["name"] == self.output_name)
                if last.get("recipe_id") != recipe_id or last.get("state") != "completed" or count <= self.before:
                    return None, "craft produced no verified output"
                self.result = "crafted " + self.output_name + "; verified own inventory gain"
        else:
            args = operation["arguments"]
            item = next((i for i in inv.get("items", []) if i["item_id"] == args["item_id"]), None)
            if self.stage == "ready":
                if item is None:
                    return None, "selected item no longer exists"
                self.before = dict(item)
                if operation["tool"]=="inventory_move":
                    destination=next((i for i in inv.get("items",[]) if i["x"]==args["to_x"] and i["y"]==args["to_y"]),None)
                    self.destination_before=dict(destination) if destination else None
                self.stage = "verify"
                return operation, None
            if self.stage == "verify":
                if operation["tool"] == "inventory_use":
                    changed = (item is None or item.get("stack") != self.before.get("stack") or
                               item.get("equipped") != self.before.get("equipped"))
                else:
                    destination = next((i for i in inv.get("items", []) if i["x"] == args["to_x"] and i["y"] == args["to_y"]), None)
                    same_item_moved = item is not None and item["x"]==args["to_x"] and item["y"]==args["to_y"] and (
                        self.before["x"]!=args["to_x"] or self.before["y"]!=args["to_y"])
                    prior_stack = (self.destination_before or {}).get("stack",0)
                    changed = same_item_moved or (destination is not None and destination["name"]==self.before["name"] and
                        destination["stack"]==prior_stack+args["amount"] and
                        (item or {}).get("stack",0)==self.before["stack"]-args["amount"])
                if not changed:
                    return None, "inventory operation had no verified change"
                self.result = "inventory change verified"
        self.stage = "closing"
        return action("close_inventory")
