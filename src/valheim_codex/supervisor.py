import fcntl
import hashlib
import json
import logging
import signal
import threading
import time
from .codex import AppServer
from .config import private_write
from .protocol import LocalClient
from .journal import PlayJournal
from .progress import Progress
from .awake import Awake
from .motion import MotionHeartbeat

LOG = logging.getLogger("supervisor")


def wait_for_focus(client, stopped, timeout=30):
    """Allow launching from a terminal without weakening loss-of-focus safety."""
    health = client.call("health")
    bridge = health.get("bridge", {})
    if bridge.get("reason") != "Game is not focused":
        return
    print("Switch to Valheim within 30 seconds. No model or gameplay actions start until it is focused.", flush=True)
    deadline = time.monotonic() + timeout
    while not stopped.wait(0.5):
        bridge = client.call("health").get("bridge", {})
        if bridge.get("reason") != "Game is not focused":
            # Leave one end-of-frame capture interval for the first observation.
            stopped.wait(0.7)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Valheim did not gain focus; start again when ready")


def run(config, max_turns=None, app_factory=AppServer):
    client = LocalClient(config)
    stopped = threading.Event()
    app = None
    awake = None
    motion = None
    journal = None
    failure = None
    lockfile = open(config.home / "run/supervisor.lock", "a+")
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lockfile.close()
        raise RuntimeError("A Valheim supervisor is already running")
    lockfile.seek(0); lockfile.truncate(); lockfile.write(str(__import__("os").getpid())); lockfile.flush()
    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, lambda *_: stopped.set())
    key = hashlib.sha256(config.settings["world_id"].encode()).hexdigest()[:16]
    session_file = config.home / "run" / ("session-" + key + ".json")
    try:
        # Preflight BEFORE authentication/model startup. Missing game cannot start a model loop.
        wait_for_focus(client, stopped)
        if stopped.is_set():
            return
        context = client.request("/context", {})
        if not context["bridge"].get("ready"):
            raise RuntimeError("Verified game bridge required")
        awake = Awake()
        client.request("/control/stop", {})
        preparation_epoch = client.request("/context", {})["epoch"]
        app = app_factory(config)
        saved = json.loads(session_file.read_text()) if session_file.exists() else {}
        previous = saved.get("thread_id")
        # App-server compaction retains recent image-bearing user messages. Real
        # measurement still showed ~65k input tokens after repeated compactions.
        # Use bounded working windows with an explicit durable handoff instead.
        if isinstance(app, AppServer) and (not saved.get("compact_context") or saved.get("window_turns", 0) >= 8):
            previous = None
        try:
            thread = app.start_thread(previous)
        except RuntimeError as exc:
            if previous and str(exc) == "Codex thread/resume failed: -32600":
                # A saved working window may no longer be resumable. Starting a
                # fresh one keeps the same checked model/policy and the durable
                # character, goals and recent-action checkpoint below.
                previous = None
                thread = app.start_thread()
                print("Saved visual session unavailable; restored character memory and goals in a fresh working session.", flush=True)
            else:
                raise
        window_turns = saved.get("window_turns", 0) if previous else 0
        def checkpoint(progress, last_result):
            private_write(session_file, json.dumps({"thread_id": thread, "world_id": config.settings["world_id"],
                "bounded_context": True, "compact_context": True, "window_turns": window_turns, "recent_actions": list(progress.recent),
                "last_result": last_result}))
        prepared = client.request("/context", {})
        if stopped.is_set() or prepared["epoch"] != preparation_epoch or prepared["bridge"].get("pause_reason") not in (None, "local operator"):
            raise InterruptedError("Gameplay stopped during model preparation")
        client.request("/control/resume", {})
        stopped.wait(0.3)
        print("Valheim supervisor active. Ctrl-C or scripts/stop.sh stops and releases controls.", flush=True)
        total = min(max_turns or config.settings["max_turns_per_run"], config.settings["max_turns_per_run"])
        journal = PlayJournal(config)
        print("Playtest evidence: " + str(journal.path), flush=True)
        last_result = saved.get("last_result")
        stale_decisions = 0
        progress = Progress()
        progress.recent.extend(saved.get("recent_actions", [])[-6:])
        checkpoint(progress, last_result)
        motion = MotionHeartbeat(client, client.request("/context", {})["epoch"])
        for _ in range(total):
            if stopped.is_set():
                break
            observed_at = time.monotonic()
            context = client.request("/context", {})
            if context["paused"] or context["bridge"].get("paused"):
                break
            epoch = context["epoch"]
            context["status"] = client.call("get_status")
            context["last_action_result"] = last_result
            context = progress.context(context)
            context["pacing"] = {"last_decision_seconds": round(getattr(app, "last_decision_seconds", 0), 1),
                "guidance": "The body continues during inference. Plan beyond the current leg when continuing toward your goal; halt for a deliberate rest or inspection."}
            image = client.call("observe_player_view")
            for content in image.get("content", []):
                if content.get("type") == "text":
                    context["view"] = json.loads(content["text"])
            journal.observation(context["status"], image)
            def should_stop():
                if stopped.is_set() or motion.failure:
                    return True
                try:
                    return client.request("/health", timeout=1).get("paused", True)
                except Exception:
                    return True
            started = time.monotonic()
            decision = app.decide(context, image, should_stop)
            app.last_decision_seconds = time.monotonic() - started
            window_turns += 1
            journal.decision(decision)
            # A slow model answer is never permission to act on an old image.
            # Leave a margin for the final loopback round trip; retry from a new
            # observation, with a bounded streak if inference remains too slow.
            if time.monotonic() - observed_at >= config.settings["max_observation_age_seconds"] * 0.9:
                stale_decisions += 1
                last_result = {"ok": False, "error": "Decision discarded because its observation expired; observe again"}
                journal.result(last_result, time.monotonic() - started, getattr(app, "last_usage", {}))
                checkpoint(progress, last_result)
                LOG.warning("discarded stale model decision; refreshing observation")
                if stale_decisions >= 3:
                    raise RuntimeError("Three consecutive model decisions exceeded the observation age limit")
                continue
            stale_decisions = 0
            last_result = client.request("/decision", {"epoch": epoch, "observation_id": context["observation_id"], "decision": decision})
            journal.result(last_result, time.monotonic() - started, getattr(app, "last_usage", {}))
            progress.record(decision, last_result)
            checkpoint(progress, last_result)
            duration = ((decision.get("action") or {}).get("arguments", {}).get("duration_ms", 0)) / 1000
            # Let the lease complete before the next image. Leases expire in the plugin even
            # if this process dies. No 60-fps model loop and no unseen action chains.
            # Capture refreshes at most twice per second. Wait beyond that interval
            # after the action ends, or the next PNG may still show the old menu/view.
            travelling = (decision.get("action") or {}).get("tool") in ("stride", "travel_to", "approach_interact")
            # Sample the moving scene after one frame interval and plan the next
            # destination while the local controller follows the current one.
            stopped.wait(.55 if travelling else max(duration + 0.65, config.settings["decision_interval_seconds"] - (time.monotonic() - started)))
            if isinstance(app, AppServer) and (window_turns >= 8 or app.last_usage.get("inputTokens", 0) > 16000):
                if should_stop():
                    break
                thread = app.start_thread()
                window_turns = 0
                checkpoint(progress, last_result)
                print("Refreshed visual working context; character goals, memory and recent progress retained.", flush=True)
        LOG.info("supervisor stopped or reached configured turn budget")
    except BaseException as exc:
        failure = type(exc).__name__ + ": " + str(exc)[:300]
        raise
    finally:
        if motion:
            motion.close()
        try:
            client.request("/control/stop", {})
        except Exception:
            try:
                LocalClient(config, "bridge").request("/control/stop", {}, timeout=2)
            except Exception:
                pass
        if journal:
            journal.finish(failure)
        if app:
            app.close()
        if awake:
            awake.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        lockfile.close()
