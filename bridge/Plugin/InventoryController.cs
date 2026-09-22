using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using HarmonyLib;
using UnityEngine;
using UnityEngine.UI;

namespace ValheimCodexBridge
{
    // Only drives the reviewed, ordinary InventoryGui callbacks on the Unity thread.
    // No direct inventory mutations, hidden recipes, remote containers, or instant crafts.
    internal sealed class InventoryController
    {
        static readonly MethodInfo Select = InstalledBindings.Required(typeof(InventoryGui), "OnSelectedItem", new[] { typeof(InventoryGrid), typeof(ItemDrop.ItemData), typeof(Vector2i), typeof(InventoryGrid.Modifier) });
        static readonly MethodInfo Use = InstalledBindings.Required(typeof(InventoryGui), "OnRightClickItem", new[] { typeof(InventoryGrid), typeof(ItemDrop.ItemData), typeof(Vector2i) });
        static readonly MethodInfo Refresh = InstalledBindings.Required(typeof(InventoryGui), "UpdateRecipe", new[] { typeof(Player), typeof(float) });
        static readonly MethodInfo SplitOk = InstalledBindings.Required(typeof(InventoryGui), "OnSplitOk", Type.EmptyTypes);
        static readonly MethodInfo Drag = InstalledBindings.Required(typeof(InventoryGui), "SetupDragItem", new[] { typeof(ItemDrop.ItemData), typeof(Inventory), typeof(int) });
        static readonly FieldInfo Recipes = Field("m_availableRecipes"), Selected = Field("m_selectedRecipe"), Timer = Field("m_craftTimer"),
            Container = Field("m_currentContainer"), DragItem = Field("m_dragItem"), MultiCraft = Field("m_touchMultiCrafting");
        static FieldInfo Field(string name) => AccessTools.Field(typeof(InventoryGui), name) ?? throw new MissingFieldException("InventoryGui", name);
        static T Property<T>(object pair, string name) => (T)pair.GetType().GetProperty(name).GetValue(pair);
        static string Local(string text) => Localization.instance.Localize(text);
        readonly Dictionary<ItemDrop.ItemData, string> ids = new Dictionary<ItemDrop.ItemData, string>();
        Player owner;
        long world;
        bool closing;
        Recipe pending;
        int beforeCraft;
        object lastCraft;
        public bool Owned => owner != null;
        InventoryGui Gui => InventoryGui.instance;
        bool Busy => Gui && (float)Timer.GetValue(Gui) >= 0;
        public bool PanelSafe => Gui && !(Container.GetValue(Gui) is Container container && container) &&
            !Gui.m_splitDialog.IsActive && !Gui.m_variantDialog.gameObject.activeSelf &&
            !Gui.IsSkillsPanelOpen && !Gui.IsTextPanelOpen && !Gui.IsTrophisPanelOpen && !Gui.IsAchievementsPanelOpen;
        public static void Verify()
        {
            if (Timer.FieldType != typeof(float) || MultiCraft.FieldType != typeof(bool)) throw new InvalidOperationException("Inventory GUI binding changed");
            foreach (string name in new[] { "Recipe", "ItemData", "InterfaceElement", "CanCraft" })
                if (Selected.FieldType.GetProperty(name) == null) throw new MissingMemberException("RecipeDataPair", name);
        }
        string Id(ItemDrop.ItemData item)
        {
            if (item == null) return "";
            if (!ids.TryGetValue(item, out string id)) ids[item] = id = Guid.NewGuid().ToString("N");
            return id;
        }
        Recipe SelectedRecipe => Gui ? Property<Recipe>(Selected.GetValue(Gui), "Recipe") : null;
        int Count(string name) => owner.GetInventory().GetAllItems().Where(i => i.m_shared.m_name == name).Sum(i => i.m_stack);
        void CompleteCraft()
        {
            if (!pending || Busy || !owner) return;
            int delta = Count(pending.m_item.m_itemData.m_shared.m_name) - beforeCraft;
            lastCraft = Json.Obj("recipe_id", pending.name, "state", delta > 0 ? "completed" : "failed", "output_delta", delta);
            pending = null;
        }
        public void Tick(BridgeEngine engine)
        {
            if (!Owned) return;
            if (engine == null || engine.Paused || owner != Player.m_localPlayer || ZNet.World == null || ZNet.World.m_uid != world || !Application.isFocused || owner.IsDead())
            { Cancel(); return; }
            if (ZInput.GetMouseButton(0) || ZInput.GetMouseButton(1) || ZInput.GetKeyDown(KeyCode.Escape) || ZInput.GetButtonDown("Inventory") || ZInput.GetButtonDown("JoyButtonB"))
            {
                if (Busy) Gui.m_craftCancelButton.onClick.Invoke();
                pending = null; owner = null; ids.Clear();
                engine.Stop("physical inventory takeover"); return;
            }
            CompleteCraft();
            if (!InventoryGui.IsVisible())
            {
                bool expected = closing;
                owner = null; ids.Clear(); closing = false;
                if (!expected) engine.Stop("inventory closed outside bridge");
            }
        }
        public void AdoptStationPanel()
        {
            var p = Player.m_localPlayer;
            // Called only after a bridge-issued normal interaction opened this panel.
            if (Owned || !p || !Gui || !InventoryGui.IsVisible() || Gui.IsContainerOpen() || !p.GetCurrentCraftingStation() || p.GetCurrentCraftingStation().m_upgrader) return;
            owner = p; world = ZNet.World.m_uid; ids.Clear(); closing = false;
            Gui.OnTabCraftPressed();
        }
        public void Cancel()
        {
            if (!Owned) return;
            if (pending) lastCraft = Json.Obj("recipe_id", pending.name, "state", "cancelled");
            pending = null;
            if (Gui) Gui.Hide();
            owner = null; closing = false; ids.Clear();
        }
        public object Snapshot()
        {
            if (!Owned || closing || !Gui || !InventoryGui.IsVisible() || !PanelSafe || owner != Player.m_localPlayer)
                return Json.Obj("open", false, "last_craft", lastCraft);
            CompleteCraft();
            var inv = owner.GetInventory();
            if (Gui.m_playerGrid.GetInventory() != inv) return Json.Obj("open", true, "loading", true);
            var selected = SelectedRecipe;
            var recipes = ((IEnumerable)Recipes.GetValue(Gui)).Cast<object>().Where(p => Property<ItemDrop.ItemData>(p, "ItemData") == null).Select(p => {
                var r = Property<Recipe>(p, "Recipe");
                return Json.Obj("recipe_id", r.name, "name", Local(r.m_item.m_itemData.m_shared.m_name), "amount", r.m_amount,
                    "requirements_met", owner.HaveRequirements(r, false, 1),
                    "station", r.GetRequiredStation(1) ? Local(r.GetRequiredStation(1).m_name) : null,
                    "station_level", r.GetRequiredStationLevel(1), "one_ingredient_only", r.m_requireOnlyOneIngredient,
                    "materials", r.m_resources.Where(q => q.m_resItem && !q.m_upgraderResource && q.GetAmount(1) > 0 && (!r.m_requireOnlyOneIngredient || owner.IsKnownMaterial(q.m_resItem.m_itemData.m_shared.m_name))).Select(q => Json.Obj("name", Local(q.m_resItem.m_itemData.m_shared.m_name), "needed", q.GetAmount(1), "have", Count(q.m_resItem.m_itemData.m_shared.m_name))).ToArray());
            }).ToArray();
            return Json.Obj("open", true, "width", inv.GetWidth(), "height", inv.GetHeight(), "weight", inv.GetTotalWeight(),
                "items", inv.GetAllItems().Select(i => Json.Obj("item_id", Id(i), "name", Local(i.m_shared.m_name), "x", i.m_gridPos.x, "y", i.m_gridPos.y,
                    "stack", i.m_stack, "quality", i.m_quality, "equipped", owner.IsItemEquiped(i), "durability", i.m_durability, "max_durability", i.GetMaxDurability(), "food_health", i.m_shared.m_food, "food_stamina", i.m_shared.m_foodStamina)).ToArray(),
                "recipes", recipes, "selected_recipe_id", selected ? selected.name : null, "crafting", Busy,
                "can_craft", !Busy && Gui.m_craftButton.interactable,
                "craft_blocker", Gui.m_craftButton.GetComponent<UITooltip>().m_text, "last_craft", lastCraft);
        }
        object Error(string message) => Json.Obj("ok", false, "error", message, "inventory", Snapshot());
        object Result() => Json.Obj("ok", true, "inventory", Snapshot());
        public object Call(string action, Dictionary<string, object> args)
        {
            if (action == "get_inventory") return Snapshot();
            if (action == "open_inventory")
            {
                if (Owned) return closing ? Error("Inventory is still closing") : Result();
                if (!Gui || InventoryGui.IsVisible()) return Error("A manual inventory panel is already open");
                owner = Player.m_localPlayer; world = ZNet.World.m_uid; ids.Clear(); closing = false;
                Gui.Show(null); Gui.OnTabCraftPressed();
                return Result();
            }
            if (!Owned || closing || !InventoryGui.IsVisible() || !PanelSafe || Gui.m_playerGrid.GetInventory() != owner.GetInventory())
                return Error("Open your own inventory first and wait until its grid is ready");
            if (action == "close_inventory")
            {
                CompleteCraft();
                if (pending) lastCraft = Json.Obj("recipe_id", pending.name, "state", "cancelled");
                pending = null; closing = true; Gui.Hide(); return Result();
            }
            if (action == "cancel_crafting")
            {
                if (Busy) Gui.m_craftCancelButton.onClick.Invoke();
                if (pending) lastCraft = Json.Obj("recipe_id", pending.name, "state", "cancelled");
                pending = null; return Result();
            }
            if (Busy) return Error("Crafting is in progress; wait or cancel it first");
            if (!Gui.InCraftTab()) return Error("Only the normal Craft tab is supported");
            if (DragItem.GetValue(Gui) != null) return Error("Inventory cursor is holding an item; close inventory to clear it");
            if (action == "select_recipe")
            {
                var match = ((IEnumerable)Recipes.GetValue(Gui)).Cast<object>().FirstOrDefault(p => Property<Recipe>(p,"Recipe").name == (string)args["recipe_id"] && Property<ItemDrop.ItemData>(p,"ItemData") == null);
                if (match == null) return Error("Recipe is not in the current known Craft list");
                Property<GameObject>(match, "InterfaceElement").GetComponent<Button>().onClick.Invoke();
                Refresh.Invoke(Gui, new object[] { owner, 0f }); return Result();
            }
            if (action == "craft_selected")
            {
                Recipe r = SelectedRecipe;
                if (!r || r.name != (string)args["recipe_id"]) return Error("Selected recipe changed; select the observed recipe first");
                if (Property<ItemDrop.ItemData>(Selected.GetValue(Gui), "ItemData") != null || ZInput.GetButton("AltPlace") || ZInput.GetButton("JoyLStick") || (bool)MultiCraft.GetValue(Gui))
                    return Error("Only one normal craft is supported");
                Refresh.Invoke(Gui, new object[] { owner, 0f });
                if (!Gui.m_craftButton.interactable || !owner.HaveRequirements(r, false, 1)) return Error("Craft requirements or station are not satisfied");
                if (!owner.GetInventory().CanAddItem(r.m_item.gameObject, r.GetAmount(1, out _, out _))) return Error("Inventory has no room for the craft output");
                beforeCraft = Count(r.m_item.m_itemData.m_shared.m_name);
                Gui.m_craftButton.onClick.Invoke();
                if (!Busy) return Error("Game did not start crafting");
                pending = r; lastCraft = Json.Obj("recipe_id", r.name, "state", "started"); return Result();
            }
            var inv = owner.GetInventory();
            var item = inv.GetAllItems().FirstOrDefault(i => ids.TryGetValue(i, out string id) && id == (string)args["item_id"]);
            if (item == null) return Error("Item ID is stale; inspect the current inventory");
            if (action == "inventory_use")
            {
                Use.Invoke(Gui, new object[] { Gui.m_playerGrid, item, item.m_gridPos });
                return Json.Obj("ok", true, "submitted", true, "note", "Normal use/equip requested; verify equipment or food in next status", "inventory", Snapshot());
            }
            if (action == "inventory_move")
            {
                int x = Convert.ToInt32(args["to_x"]), y = Convert.ToInt32(args["to_y"]), amount = Convert.ToInt32(args["amount"]);
                if (x >= inv.GetWidth() || y >= inv.GetHeight()) return Error("Destination is outside your own inventory grid");
                var target = inv.GetItemAt(x, y);
                if (Id(target) != (string)args["expected_destination_id"]) return Error("Destination changed; inspect before replacing it");
                if (target == item || amount < 1 || amount > item.m_stack) return Error("Invalid stack amount or unchanged destination");
                var modifier = amount == item.m_stack ? InventoryGrid.Modifier.Select : InventoryGrid.Modifier.Split;
                try
                {
                    Select.Invoke(Gui, new object[] { Gui.m_playerGrid, item, item.m_gridPos, modifier });
                    if (modifier == InventoryGrid.Modifier.Split)
                    {
                        if (!Gui.m_splitDialog.IsActive) return Error("Game did not open the split dialog");
                        Gui.m_splitDialog.SliderValue = amount;
                        SplitOk.Invoke(Gui, null);
                    }
                    Select.Invoke(Gui, new object[] { Gui.m_playerGrid, target, new Vector2i(x,y), InventoryGrid.Modifier.Select });
                    if (DragItem.GetValue(Gui) != null) return Error("Game rejected or only partly completed the move");
                    return Result();
                }
                finally { Drag.Invoke(Gui, new object[] { null, null, 1 }); }
            }
            throw new ArgumentException("Unknown inventory action");
        }
    }
}
