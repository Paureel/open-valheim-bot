import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from .config import Config, ROOT, private_write
from .doctor import inspect_machine
from .protocol import LocalClient


@contextmanager
def local_service(config):
    """One service across MCP clients/supervisors; owned child exits with its owner."""
    import fcntl
    owned = None
    client = LocalClient(config)
    try:
        with open(config.home / "run/service-start.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                client.request("/health", timeout=1)
            except Exception:
                env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
                owned = subprocess.Popen([sys.executable, "-m", "valheim_codex", "--home", str(config.home), "service"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
                for _ in range(30):
                    if owned.poll() is not None:
                        raise RuntimeError("Local service failed to start; inspect logs/service.log")
                    time.sleep(0.1)
                    try:
                        client.request("/health", timeout=0.5)
                        break
                    except Exception:
                        pass
                else:
                    raise RuntimeError("Local service startup timed out")
        yield client
    finally:
        if owned:
            owned.terminate()
            try:
                owned.wait(timeout=15)
            except subprocess.TimeoutExpired:
                owned.kill(); owned.wait(timeout=5)


def stdio(config):
    with local_service(config) as client:
        stdio_loop(client)


def stdio_loop(client):
    """Codex-compatible newline-delimited MCP; stdout is protocol only."""
    for line in sys.stdin:
        identifier = None
        try:
            if len(line) > 65536:
                raise ValueError("Request too large")
            request = json.loads(line)
            identifier = request.get("id")
            if "id" not in request:
                # Stateless transport has no initialization or session mutation.
                continue
            response = client.request("/mcp", request)
        except Exception:
            response = {"jsonrpc": "2.0", "id": identifier,
                        "error": {"code": -32000, "message": "Local Valheim service unavailable or request invalid. Run scripts/service.sh."}}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def serve(config):
    from .service import LocalServer, Service, setup_logging
    setup_logging(config)
    service = Service(config)
    server = LocalServer(service)
    service.start_polling()
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        print("Valheim local service listening on 127.0.0.1:" + str(config.settings["service_port"]), flush=True)
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        service.close()


def start(config, max_turns, seconds=None, shadow=False, legacy=False):
    from .service import setup_logging
    if legacy:
        from .supervisor import run
    else:
        from .dual_supervisor import run
    setup_logging(config)
    with local_service(config):
        if legacy:
            run(config, max_turns=max_turns)
        else:
            run(config, max_turns=max_turns, seconds=seconds, shadow=shadow)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="ValheimCodex local player services")
    parser.add_argument("--home", help="Application support directory (default: ~/Library/Application Support/ValheimCodex)")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "service", "stop", "resume", "shutdown", "status", "stdio", "codex-smoke"):
        subs.add_parser(name)
    st = subs.add_parser("start"); st.add_argument("--max-turns", type=int)
    st.add_argument("--seconds", type=float, default=600)
    st.add_argument("--shadow", action="store_true", help="Observe local decisions without sending controls or speech")
    st.add_argument("--legacy", action="store_true", help="Explicit serial Luna diagnostic fallback")
    dr = subs.add_parser("doctor"); dr.add_argument("--game-dir")
    obs = subs.add_parser("observe", help="Read-only local brain visualization")
    obs.add_argument("--port", type=int, default=8733)
    args = parser.parse_args()
    if args.command == "doctor":
        print(json.dumps(inspect_machine(args.game_dir), indent=2)); return
    config = Config(args.home).initialize()
    if args.command == "observe":
        from .observer import serve as observe
        if not 1024 <= args.port <= 65535 or args.port in (config.settings["service_port"], config.settings["bridge_port"]):
            raise ValueError("Choose a separate unprivileged observer port")
        observe(config, args.port); return
    if args.command == "init":
        from .memory import Memory
        memory = Memory(config.home / "memory.sqlite3", config.settings["world_id"])
        memory.close()
        print("Local configuration and memory directory prepared: " + str(config.home)); return
    if args.command == "service":
        serve(config); return
    if args.command == "start":
        if not 1 <= args.seconds <= 1800:
            raise ValueError("Run duration must be 1–1800 seconds")
        start(config, args.max_turns, args.seconds, args.shadow, args.legacy); return
    if args.command == "stdio":
        stdio(config); return
    if args.command == "codex-smoke":
        from .codex import AppServer
        app = AppServer(config, authenticate=False)
        try:
            # No thread creation or model request. Handshake and schema/config checks only.
            info = app.rpc("config/read", {"includeLayers": False})
            effective = info["config"]
            if effective.get("features", {}).get("shell_tool") is not False:
                raise RuntimeError("Shell isolation was not applied")
            print("Installed Codex app-server handshake/config check passed; no model called.")
        finally:
            app.close()
        return
    client = LocalClient(config)
    if args.command in ("stop", "resume", "shutdown"):
        try:
            result = client.request("/control/" + args.command, {})
        except Exception:
            if args.command != "stop":
                raise
            result = LocalClient(config, "bridge").request("/control/stop", {}, timeout=2)
        print(json.dumps(result)); return
    print(json.dumps(client.call("health"), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, TimeoutError) as exc:
        print("ValheimCodex: " + str(exc), file=sys.stderr)
        sys.exit(1)
