"""Operator-only installers. These functions are never exposed as gameplay tools."""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from .config import ROOT, private_write


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install_files(source, destination, backups, label):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    backup = Path(backups) / (label + "-" + str(time.time_ns()))
    backup.mkdir(parents=True, mode=0o700)
    manifest = {"destination": str(destination), "files": []}
    manifest_path = backup / "manifest.json"
    # First back up EVERY file that will change; perform no writes to the target yet.
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink source not supported")
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        target = destination / rel
        if not target.resolve().is_relative_to(destination):
            raise ValueError("Destination symlink escapes installation")
        if target.exists():
            saved = backup / "original" / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        manifest["files"].append({"relative": str(rel), "installed_sha256": digest(path), "existed": target.exists()})
    private_write(manifest_path, json.dumps(manifest, indent=2))
    for entry in manifest["files"]:
        path = source / entry["relative"]
        target = destination / entry["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return manifest_path


def restore(manifest_path):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    destination = Path(manifest["destination"]).resolve()
    preserved = []
    for entry in manifest["files"]:
        rel = Path(entry["relative"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe manifest path")
        target = destination / rel
        if not target.resolve().is_relative_to(destination):
            raise ValueError("Destination symlink escapes installation")
        if not target.exists():
            continue
        if digest(target) != entry["installed_sha256"]:
            preserved.append(str(target))
            continue
        if entry["existed"]:
            shutil.copy2(manifest_path.parent / "original" / rel, target)
        else:
            target.unlink()
    return preserved


def register_mcp(config):
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Codex CLI not found")
    name = "valheim-codex"
    current = subprocess.run([binary, "mcp", "get", name, "--json"], capture_output=True, text=True)
    if current.returncode == 0:
        data = json.loads(current.stdout)
        if data.get("transport", {}).get("command") == str(ROOT / "scripts/mcp.sh"):
            return "MCP already registered for this project"
        raise RuntimeError("An unrelated valheim-codex MCP entry exists; refusing to replace it")
    config_file = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    backup = config.home / "backups" / ("codex-config-" + str(time.time_ns()) + ".toml")
    if config_file.exists():
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(config_file, backup)
        os.chmod(backup, 0o600)
    result = subprocess.run([binary, "mcp", "add", name, "--", str(ROOT / "scripts/mcp.sh")], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("codex mcp add failed; existing configuration backup preserved")
    private_write(config.home / "mcp-registration.json", json.dumps({"name": name, "command": str(ROOT / "scripts/mcp.sh")}))
    return "Registered valheim-codex MCP; previous Codex configuration backed up"


def unregister_mcp(config):
    record = config.home / "mcp-registration.json"
    if not record.exists():
        return
    data = json.loads(record.read_text())
    binary = shutil.which("codex")
    result = subprocess.run([binary, "mcp", "get", data["name"], "--json"], capture_output=True, text=True)
    if result.returncode == 0:
        current = json.loads(result.stdout)
        if current.get("transport", {}).get("command") != data["command"]:
            raise RuntimeError("MCP configuration changed since installation; preserving it")
        subprocess.run([binary, "mcp", "remove", data["name"]], check=True, capture_output=True)
    record.unlink()
