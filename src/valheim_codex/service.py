import hmac
import json
import logging
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler

from .memory import Memory, utc
from .policy import SpeechGate, validate_decision
from .protocol import GAME_TOOLS, MEMORY_TOOLS, TOOLS, LocalClient, text_result, validate_tool

LOG = logging.getLogger("service")


def setup_logging(config):
    handler = RotatingFileHandler(config.home / "logs/service.log", maxBytes=2_000_000, backupCount=4)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


class Service:
    def __init__(self, config, bridge=None):
        self.config = config
        self.memory = Memory(config.home / "memory.sqlite3", config.settings["world_id"])
        self.memory.prune_conversations(config.settings["conversation_retention_days"])
        self.bridge = bridge or LocalClient(config, "bridge")
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.poll_lock = threading.RLock()
        self.paused = True
        self.epoch = str(uuid.uuid4())
        self.reason = "Local resume required"
        self.session, self.cursor = None, 0
        self.speech = SpeechGate(config.settings)
        self.closed = threading.Event()
        self.thread = None
        self.observations = {}

    def stop(self, reason):
        with self.lock:
            self.paused, self.reason, self.epoch = True, reason, str(uuid.uuid4())
        LOG.info("stop: %s", reason)
        try:
            self.bridge.request("/control/stop", {}, timeout=2)
        except Exception:
            LOG.warning("bridge unavailable during stop; in-plugin input leases still expire")
        return {"ok": True, "paused": True}

    def ready(self):
        health = self.bridge.request("/health")
        if health.get("ready") is not True:
            raise RuntimeError("Bridge not ready: " + str(health.get("reason", "verified game adapter required")))
        if health.get("world_id") != self.config.settings["world_id"] or health.get("character_name") != self.config.settings["character_name"]:
            raise RuntimeError("Wrong world or character")
        # .NET round-trip timestamps have seven fractional digits; Python 3.9 only
        # accepts three or six. Normalize without changing the timestamp's meaning.
        timestamp = health["main_thread_utc"].replace("Z", "+00:00")
        timestamp = re.sub(r"(\.\d{6})\d+(?=[+-]|$)", r"\1", timestamp)
        stamp = datetime.fromisoformat(timestamp)
        if not -2 <= (datetime.now(timezone.utc) - stamp).total_seconds() < 5:
            raise RuntimeError("Game main-thread heartbeat is stale")
        return health

    def resume(self):
        # Resume cancels queued bridge work. Do not cancel an in-flight chat poll
        # and let its watchdog misinterpret that cancellation as disconnection.
        # Poll may itself resume for a verified owner, hence the reentrant lock.
        with self.poll_lock, self.operation_lock:
            self.ready()
            with self.lock:
                epoch = self.epoch
            try:
                self.bridge.request("/control/resume", {})
                # The bridge publishes health at the end of a Unity tick. Keep
                # the gateway paused until it acknowledges resume, so callers and
                # the polling watchdog cannot mistake the previous snapshot for
                # a new emergency pause. Stop never waits on operation_lock.
                deadline = time.monotonic() + 2
                while True:
                    with self.lock:
                        if epoch != self.epoch:
                            raise RuntimeError("Resume interrupted")
                    if not self.ready().get("paused", True):
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Game did not acknowledge resume")
                    time.sleep(0.02)
            except Exception:
                self.stop("resume interrupted or unacknowledged")
                raise
            with self.lock:
                interrupted = epoch != self.epoch
                if not interrupted:
                    self.paused, self.reason, self.epoch = False, "Running", str(uuid.uuid4())
            if interrupted:
                self.stop("resume interrupted by stop")
                raise RuntimeError("Resume interrupted")
        LOG.info("local operator resumed")
        return {"ok": True}

    def travel_heartbeat(self, epoch):
        with self.operation_lock:
            with self.lock:
                if self.paused or epoch != self.epoch:
                    return {"ok": False}
            # The bridge checks its own pause/focus/world and does not start or
            # extend a destination. No travel is possible without a model intent.
            return self.bridge.request("/control/travel-heartbeat", {}, timeout=1)

    def poll(self):
        with self.poll_lock:
            result = self.bridge.call("get_chat", {"after_event_id": self.cursor, "limit": 100})
            if result["session_id"] != self.session:
                self.session, self.cursor = result["session_id"], 0
                result = self.bridge.call("get_chat", {"after_event_id": 0, "limit": 100})
            for event in result["events"]:
                event["trusted"] = self.config.is_trusted(event)
                if self.memory.add_chat(self.session, event, self.config.settings["conversation_retention_days"]):
                    LOG.info("incoming chat session=%s event=%s verified=%s", self.session, event["event_id"], event.get("identity_verified") is True)
                    # The real plugin should stop first, on the same frame as chat arrives.
                    if event.get("identity_verified") is True and event.get("sender_id") in self.config.owners:
                        command = event["text"].strip().lower()
                        if command in ("!codex stop", "!codex pause"):
                            self.stop("verified owner")
                        elif command == "!codex resume":
                            self.resume()
            if result.get("dropped"):
                LOG.warning("chat ring overflow; missing events are not fabricated")
            self.cursor = result["cursor"]

    def context(self):
        self.poll()
        health = self.ready()
        conversation = self.memory.conversation(self.config.settings["conversation_buffer_size"])
        # Re-evaluate current trust after config changes/restarts, never trust stored annotations.
        for event in conversation:
            event["trusted"] = self.config.is_trusted(event)
        with self.lock:
            observation = str(uuid.uuid4())
            self.observations[observation] = (self.epoch, time.monotonic(), self.session)
            if len(self.observations) > 32:
                del self.observations[next(iter(self.observations))]
            return {"epoch": self.epoch, "paused": self.paused, "bridge": health,
                "conversation": conversation, "goals": self.memory.goals(),
                "social": {"seconds_since_speech": round(min(3600, time.monotonic() - self.speech.last)),
                           "comment_due": time.monotonic() - self.speech.last >= 30},
                "memories": self.memory.recall(limit=20), "settings": self.config.settings,
                "session_id": self.session, "observation_id": observation}

    def call(self, name, arguments, expected_epoch=None):
        validate_tool(name, arguments)
        if expected_epoch is not None:
            with self.lock:
                if self.paused or self.epoch != expected_epoch:
                    raise RuntimeError("Decision cancelled")
        if name == "health":
            try:
                bridge = self.bridge.request("/health", timeout=2)
            except Exception:
                bridge = {"ready": False, "reason": "Bridge unreachable"}
            return text_result({"ok": True, "paused": self.paused, "reason": self.reason, "bridge": bridge})
        if name in MEMORY_TOOLS:
            return text_result(self.memory.call(name, arguments))
        if name == "stop":
            return text_result(self.stop("MCP emergency stop"))
        readonly = name in ("get_status", "get_chat", "observe_player_view", "get_inventory")
        with self.operation_lock:
            with self.lock:
                if not readonly and self.paused:
                    raise RuntimeError("Emergency pause is latched")
                epoch = self.epoch
            if not readonly:
                health = self.ready()
                if health.get("paused"):
                    raise RuntimeError("Bridge pause is latched")
                if arguments.get("duration_ms", 0) > self.config.settings["max_action_ms"]:
                    raise ValueError("Duration exceeds configured maximum")
                if not self.config.settings["combat_enabled"] and (name in ("primary_attack", "secondary_attack", "block") or
                        name == "motor" and (arguments.get("block") or arguments.get("button") == "primary_attack")):
                    raise ValueError("Combat disabled")
                with self.lock:
                    if self.paused or self.epoch != epoch or (expected_epoch is not None and self.epoch != expected_epoch):
                        raise RuntimeError("Decision cancelled")
            normalized = self.speech.check(arguments["text"]) if name == "send_chat" else None
            result = self.bridge.call(name, arguments)
            if name == "send_chat":
                self.speech.sent(normalized)
                # Own speech context even if the client doesn't echo sent chat back.
                self.memory.add_chat("outgoing-" + self.epoch, {"event_id": time.time_ns(), "timestamp": utc(),
                    "sender": self.config.settings["character_name"], "sender_id": None,
                    "identity_verified": False, "channel": arguments.get("type", "normal"),
                    "text": arguments["text"], "direction": "outgoing"}, self.config.settings["conversation_retention_days"])
                LOG.info("outgoing chat sent")
            if name == "observe_player_view":
                return result  # native MCP image content
            return text_result(result)

    def decision(self, payload):
        context = self.context()
        if payload.get("epoch") != context["epoch"] or context["paused"]:
            raise RuntimeError("Decision invalidated by stop/resume")
        with self.lock:
            observation = self.observations.pop(payload.get("observation_id"), None)
        if observation is None or observation[0] != context["epoch"] or observation[2] != context["session_id"]:
            raise RuntimeError("Unknown or already-used observation")
        if time.monotonic() - observation[1] > self.config.settings["max_observation_age_seconds"]:
            raise RuntimeError("Observation expired; observe again before acting")
        decision = payload["decision"]
        validate_decision(decision, self.config, context["conversation"], context["session_id"])
        results = []
        # Check epoch around each external side effect. No arbitrary tool dispatch from chat.
        action = decision["action"]
        operations = ([action] if action else []) + decision["memories"]
        speech = decision["speech"]
        skipped_speech = None
        if speech:
            try:
                self.speech.check(speech["text"], speech["voluntary"])
                operations.append({"tool": "send_chat", "arguments": {"text": speech["text"], "type": speech["type"]}})
            except ValueError as exc:
                skipped_speech = str(exc)
        for op in operations:
            with self.lock:
                if self.paused or self.epoch != payload["epoch"]:
                    raise RuntimeError("Decision cancelled")
            results.append(self.call(op["tool"], op["arguments"], expected_epoch=payload["epoch"]))
        # Log a bounded, single-line decision note. Never raw app-server or auth payloads.
        LOG.info("decision: %s", decision["note"].replace("\n", " ").replace("\r", " "))
        return {"ok": True, "results": results, "skipped_speech": skipped_speech}

    def start_polling(self):
        def run():
            failed = False
            while not self.closed.wait(0.25):
                try:
                    self.poll()
                    if not self.paused:
                        health = self.ready()
                        if health.get("paused"):
                            self.stop("bridge paused: " + health.get("pause_reason", "unspecified"))
                    failed = False
                except Exception as exc:
                    # A local stop deliberately cancels pending bridge work.
                    # Its cancelled poll must not issue a second stop that races
                    # with the operator's next preparation/context request.
                    if not failed and not self.paused:
                        self.stop("bridge unavailable: " + str(exc)[:200])
                    failed = True
        self.thread = threading.Thread(target=run, daemon=True, name="valheim-chat")
        self.thread.start()

    def close(self):
        self.closed.set()
        self.stop("service shutdown")
        if self.thread:
            self.thread.join(timeout=12)
        self.memory.close()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, service):
        self.service = service
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", service.config.settings["service_port"]), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(False):
            request.close()
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # no request header/token logging

    def respond(self, status, value=None):
        raw = b"" if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        config = self.server.service.config
        if self.client_address[0] != "127.0.0.1" or self.headers.get("Host") != "127.0.0.1:" + str(config.settings["service_port"]) or self.headers.get("Origin") is not None:
            self.respond(403, {"error": "Local non-browser clients only"})
            return False
        actual = self.headers.get("Authorization", "")
        if not hmac.compare_digest(actual, "Bearer " + config.token("service")):
            self.respond(401, {"error": "Unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/health":
            self.respond(200, {"ok": True, "paused": self.server.service.paused, "reason": self.server.service.reason})
        else:
            self.respond(405, {"error": "Use POST /mcp"})

    def do_POST(self):
        if not self.authorized():
            return
        identifier = None
        try:
            if self.headers.get("Transfer-Encoding") or not self.headers.get("Content-Type", "").startswith("application/json"):
                self.respond(415, {"error": "JSON with Content-Length required"})
                return
            length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= length <= 65536:
                self.respond(413, {"error": "Invalid body length"})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete request")
            request = json.loads(raw)
            service = self.server.service
            if self.path == "/control/stop":
                self.respond(200, service.stop("local operator")); return
            if self.path == "/control/shutdown":
                self.respond(200, service.stop("local service shutdown"))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == "/control/resume":
                self.respond(200, service.resume()); return
            if self.path == "/control/travel-heartbeat":
                self.respond(200, service.travel_heartbeat(request.get("epoch"))); return
            if self.path == "/control/motor":
                epoch = request.get("epoch")
                if not isinstance(epoch, str):
                    raise ValueError("Motor epoch required")
                self.respond(200, service.call("motor", request["arguments"], expected_epoch=epoch)); return
            if self.path == "/context":
                self.respond(200, service.context()); return
            if self.path == "/decision":
                self.respond(200, service.decision(request)); return
            if self.path != "/mcp":
                self.respond(404, {"error": "Unknown route"}); return
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                raise ValueError("Invalid JSON-RPC request")
            identifier = request.get("id")
            if "id" not in request:
                self.respond(202); return
            method = request["method"]
            if method == "initialize":
                offered = request.get("params", {}).get("protocolVersion")
                version = offered if offered in ("2024-11-05", "2025-03-26", "2025-06-18") else "2025-03-26"
                result = {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": "valheim-codex", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    p = request["params"]
                    result = service.call(p["name"], p.get("arguments", {}))
                except Exception as exc:
                    LOG.warning("tool failed: %s", type(exc).__name__)
                    result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
            else:
                self.respond(200, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "Unknown method"}}); return
            self.respond(200, {"jsonrpc": "2.0", "id": identifier, "result": result})
        except Exception as exc:
            LOG.warning("request failed: %s", type(exc).__name__)
            self.respond(400, {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32600, "message": str(exc)}})
