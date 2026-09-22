import json
import math
import urllib.error
import urllib.request
from .config import ROOT

TOOLS = json.loads((ROOT / "config/tools.json").read_text())
TOOL_MAP = {t["name"]: t for t in TOOLS}
GAME_TOOLS = {t["name"] for t in json.loads((ROOT / "bridge/Core/game-tools.json").read_text())}
MEMORY_TOOLS = set(TOOL_MAP) - GAME_TOOLS


def validate(value, schema):
    """Validate our deliberately small JSON Schema vocabulary without coercion."""
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                validate(value, option)
                return
            except ValueError:
                pass
        raise ValueError("Value does not match any allowed shape")
    kind = schema.get("type")
    valid = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "boolean": type(value) is bool,
             "integer": type(value) is int, "number": type(value) in (int, float), "null": value is None}
    if kind and not valid[kind]:
        raise ValueError("Expected " + kind)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Invalid choice")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(value):
            raise ValueError("Missing required arguments")
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ValueError("Unexpected arguments")
        for key, child in value.items():
            if key in props:
                validate(child, props[key])
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10000):
            raise ValueError("Too many items")
        for child in value:
            validate(child, schema.get("items", {}))
    if isinstance(value, str) and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 10000000):
        raise ValueError("Invalid string length")
    if type(value) in (int, float):
        if not math.isfinite(value) or not schema.get("minimum", -1e308) <= value <= schema.get("maximum", 1e308):
            raise ValueError("Number out of range")


def validate_tool(name, arguments):
    if name not in TOOL_MAP:
        raise ValueError("Unknown tool")
    validate(arguments, TOOL_MAP[name]["inputSchema"])


def text_result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, allow_nan=False)}], "isError": False}


def unpack(result):
    if result.get("isError"):
        raise RuntimeError(result["content"][0]["text"])
    content = result.get("content", [])
    if len(content) == 1 and content[0]["type"] == "text":
        return json.loads(content[0]["text"])
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError("Local control endpoint redirect refused")


class LocalClient:
    def __init__(self, config, target="service"):
        self.url = "http://127.0.0.1:" + str(config.settings[target + "_port"])
        self.token = config.token(target)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, data=None, timeout=5):
        request = urllib.request.Request(self.url + path, data=None if data is None else json.dumps(data, allow_nan=False).encode(),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(9_000_001)
        except urllib.error.HTTPError as exc:
            # Keep errors useful without dumping request headers, tokens, or raw payloads.
            try:
                error = json.loads(exc.read(4096)).get("error", "Local request failed")
            except (ValueError, OSError):
                error = "Local request failed"
            message = error.get("message", "Local request failed") if isinstance(error, dict) else str(error)
            raise RuntimeError(message) from None
        if len(raw) > 9_000_000:
            raise ValueError("Response too large")
        return json.loads(raw)

    def call(self, name, arguments=None):
        args = arguments or {}
        validate_tool(name, args)
        response = self.request("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return unpack(response["result"])
