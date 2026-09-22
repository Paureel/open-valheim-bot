#!/usr/bin/env python3
"""Validate reviewed hashes and reflective/Harmony bindings without running Valheim."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_hashes(managed, reviewed):
    for name, expected in reviewed.items():
        actual = hashlib.sha256((managed / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Unreviewed assembly: " + name + ". Re-inspect changed APIs before rebuilding/installing.")


def verify(managed):
    reviewed = json.loads((ROOT / "bridge/Plugin/reviewed-assemblies.json").read_text())
    verify_hashes(managed, reviewed)
    output = subprocess.check_output([str(ROOT / ".tools/dotnet/dotnet"),
        str(ROOT / "tools/AssemblyInspector/bin/Release/net10.0/AssemblyInspector.dll"),
        str(managed / "assembly_valheim.dll"), str(managed / "assembly_utils.dll")], text=True)
    report = json.loads(output)
    types = {t["name"]: t for a in report["assemblies"] for t in a["types"]}
    checks = [
        ("InventoryGui", "OnSelectedItem", ["InventoryGrid", "ItemData", "Vector2i", "Modifier"], ["grid", "item", "pos", "mod"]),
        ("InventoryGui", "OnRightClickItem", ["InventoryGrid", "ItemData", "Vector2i"], ["grid", "item", "pos"]),
        ("InventoryGui", "UpdateRecipe", ["Player", "Single"], ["player", "dt"]),
        ("InventoryGui", "OnSplitOk", [], []),
        ("InventoryGui", "SetupDragItem", ["ItemData", "Inventory", "Int32"], ["item", "inventory", "amount"]),
        ("Player", "TakeInput", [], []),
        ("Player", "UpdateHover", [], []),
        ("Player", "Interact", ["GameObject", "Boolean", "Boolean"], ["go", "hold", "alt"]),
        ("Player", "SetMouseLook", ["Vector2"], ["mouseLook"]),
        ("Player", "SetControls", ["Vector3"] + ["Boolean"] * 11,
            ["movedir", "attack", "attackHold", "secondaryAttack", "secondaryAttackHold", "block", "blockHold", "jump", "crouch", "run", "autoRun", "dodge"]),
        ("Terminal", "AddString", ["PlatformUserID", "String", "Type", "Boolean"], ["user", "text", "type", "timestamp"]),
        ("Chat", "SendText", ["Type", "String"], ["type", "text"]),
    ]
    for cls, name, parameters, names in checks:
        method = next((m for m in types[cls]["methods"] if m["name"] == name and m["parameters"] == parameters), None)
        if method is None or [n for n in method["parameter_names"] if n] != names:
            raise ValueError("Reflected/Harmony signature changed: " + cls + "." + name)
    if not any(f["name"] == "m_blocking" and f["type"] == "Boolean" for f in types["Character"]["fields"]):
        raise ValueError("Character.m_blocking changed")
    return {"game": "Valheim 1.0.15", "steam_build": "25390630", "reviewed_hashes": len(reviewed),
        "reflected_bindings": len(checks) + 1, "in_game_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("managed")
    args = parser.parse_args()
    print(json.dumps(verify(Path(args.managed).expanduser().resolve()), indent=2))
