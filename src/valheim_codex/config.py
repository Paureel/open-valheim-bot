import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOME = Path.home() / "Library/Application Support/ValheimCodex"


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".new")
    with os.fdopen(os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(text)
    temporary.replace(path)


class Config:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("VALHEIM_CODEX_HOME", DEFAULT_HOME)).expanduser().resolve()
        self.settings = json.loads((ROOT / "config/settings.json").read_text())
        local = self.home / "settings.json"
        if local.exists():
            overrides = json.loads(local.read_text())
            if set(overrides) - set(self.settings):
                raise ValueError("Unknown configuration keys")
            self.settings.update(overrides)
        for key in ["service_port", "bridge_port"]:
            if type(self.settings[key]) is not int or not 1024 <= self.settings[key] <= 65535:
                raise ValueError("Invalid local port")
        if self.settings["service_port"] == self.settings["bridge_port"]:
            raise ValueError("Service and bridge require different ports")
        for key, low, high in [("max_action_ms", 1, 1500), ("maximum_message_length", 1, 160),
                               ("conversation_buffer_size", 1, 100), ("conversation_retention_days", 1, 30),
                               ("max_turns_per_run", 1, 10000)]:
            if type(self.settings[key]) is not int or not low <= self.settings[key] <= high:
                raise ValueError("Invalid " + key)
        for key, low, high in [("decision_interval_seconds", 2, 60), ("decision_timeout_seconds", 10, 180),
                               ("max_observation_age_seconds", 5, 60),
                               ("min_seconds_between_messages", 4, 120)]:
            value = self.settings[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError("Invalid " + key)
        for key, default in json.loads((ROOT / "config/settings.json").read_text()).items():
            if type(default) is bool and type(self.settings[key]) is not bool:
                raise ValueError("Boolean required for " + key)
        if not isinstance(self.settings["world_id"], str) or not 1 <= len(self.settings["world_id"]) <= 200:
            raise ValueError("Invalid world_id")
        if self.settings["model"] is not None and (not isinstance(self.settings["model"], str) or not self.settings["model"].strip()):
            raise ValueError("Invalid model")
        if self.settings["reasoning_effort"] not in (None, "low", "medium", "high", "xhigh", "max"):
            raise ValueError("Invalid reasoning_effort")
        trust_file = self.home / "trusted-players.json"
        trust = json.loads((trust_file if trust_file.exists() else ROOT / "config/trusted-players.json").read_text())
        for name in ("owners", "trusted_players"):
            if not isinstance(trust.get(name), list) or any(not isinstance(x, str) or not x.strip() for x in trust[name]):
                raise ValueError("Trusted players must be stable ID strings")
        self.owners = frozenset(trust["owners"])
        self.trusted = self.owners | frozenset(trust["trusted_players"])

    def initialize(self):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.home, 0o700)
        for directory in ("logs", "run", "codex", "agent-workspace"):
            (self.home / directory).mkdir(exist_ok=True, mode=0o700)
        for name in ("settings.json", "trusted-players.json", "character.md"):
            if not (self.home / name).exists():
                private_write(self.home / name, (ROOT / "config" / name).read_text())
        for name in ("service.token", "bridge.token"):
            path = self.home / name
            if not path.exists():
                private_write(path, secrets.token_hex(32))
            os.chmod(path, 0o600)
        return self

    def token(self, name):
        value = (self.home / (name + ".token")).read_text().strip()
        if len(value) < 32:
            raise ValueError("Local authentication token invalid")
        return value

    def is_trusted(self, event):
        return event.get("identity_verified") is True and event.get("sender_id") in self.trusted

    def profile(self):
        path = self.home / "character.md"
        return (path if path.exists() else ROOT / "config/character.md").read_text()
