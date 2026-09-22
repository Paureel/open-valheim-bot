"""Asynchronous System 2 intentions plus fresh-pixel System 1 control."""
import fcntl
import json
import os
import signal
import threading
import time
from collections import deque
from .awake import Awake
from .brain import BrainFeed
from .config import private_write
from .intents import Intent, validate_plan
from .journal import PlayJournal
from .motor import Motor, controls
from .planner import Planner
from .protocol import LocalClient, unpack
from .skills import InventorySkill
from .supervisor import wait_for_focus
from .system_one import Worker


def snapshot(client):
    status = client.call("get_status")
    started = time.monotonic()
    image = client.call("observe_player_view")
    view = next(json.loads(c["text"]) for c in image["content"] if c.get("type") == "text")
    png = next(c["data"] for c in image["content"] if c.get("type") == "image")
    # Conservative age: include all local round-trip time, not just model time.
    captured = started - view["age_ms"] / 1000
    return {"status": status, "image": image, "view": view, "png": png, "captured_at": captured}


def run(config, max_turns=None, seconds=None, shadow=False, worker_factory=Worker, planner_factory=Planner, plan_interval=15):
    client = LocalClient(config)
    stopped = threading.Event()
    worker = planner = awake = journal = telemetry = brain = None
    failure = None
    lock = open(config.home / "run/supervisor.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("A Valheim supervisor is already running")
    lock.seek(0); lock.truncate(); lock.write(str(os.getpid())); lock.flush()
    handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, lambda *_: stopped.set())
    events = deque(maxlen=16)
    revision = 0
    intent = skill = None
    supplies_before = {}
    motor = Motor()
    totals = {"local_results": 0, "stale_results": 0, "idle_results": 0, "plans": 0, "actions": 0,
              "shadow": shadow, "events": [], "latencies_ms": [], "capture_to_control_ms": []}
    try:
        wait_for_focus(client, stopped)
        context = client.request("/context", {})
        client.request("/control/stop", {})
        prepared = client.request("/context", {})
        brain = BrainFeed(config, shadow)
        awake = Awake()
        print("Warming local OpenJev; controls remain paused.", flush=True)
        worker = worker_factory(config)
        if not shadow:
            planner = planner_factory(config, stopped)
        check = client.request("/context", {})
        if stopped.is_set() or check["epoch"] != prepared["epoch"]:
            raise InterruptedError("Preparation interrupted by operator")
        if not shadow:
            client.request("/control/resume", {})
        context = client.request("/context", {})
        epoch, session = context["epoch"], context["session_id"]
        journal = PlayJournal(config)
        brain.publish(phase="shadow" if shadow else "live")
        private_write(journal.path / "system-one.json", json.dumps(worker.identity))
        print(("Observation-only shadow" if shadow else "Luna + local OpenJev") + " active: " + str(journal.path), flush=True)
        start = time.monotonic()
        deadline = start + (seconds if seconds is not None else 600)
        next_plan = start
        next_capture = start
        last_frame = -1
        last_health = 0
        last_status = {}
        last_snapshot = None
        missing_frame_since = None
        blocked_since = None
        last_health_value = None
        last_plan_latency = 8.0
        private_write(journal.path / "system-one.jsonl", "")
        telemetry = open(journal.path / "system-one.jsonl", "a")
        def record(event):
            events.append(event)
            totals["events"].append({"at": round(time.monotonic()-start,2), "event": event})
            print(event, flush=True)
            brain.publish(activity=event[:240])
        def finish_intent(reason, invalidate=True):
            nonlocal intent, skill, revision, next_plan, blocked_since
            record(reason)
            intent = skill = None
            brain.fire(1, ["stop"], reason, intent="", objective="", thinking=False if invalidate else brain.state["thinking"])
            # An already-requested next plan may finish after ordinary arrival
            # or a deliberate rest. A hazard/task interruption invalidates it.
            if invalidate:
                revision += 1
                if planner and hasattr(planner,"cancel"):
                    planner.cancel()
            next_plan = 0
            blocked_since = None
            if not shadow:
                # halt is an epoch-checked ordinary action, never a resume.
                fresh = client.request("/context", {})
                client.request("/decision", {"epoch": epoch, "observation_id": fresh["observation_id"],
                    "decision": {"note": reason, "action": {"tool":"halt","arguments":{}},
                                 "source_event_id":None,"speech":None,"memories":[]}})
        while not stopped.is_set() and time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_health > .2:
                health = client.call("health")
                if not health["bridge"].get("ready") or (not shadow and (health["paused"] or health["bridge"].get("paused"))):
                    record("operator/game pause: " + str(health.get("reason")))
                    break
                last_health = now
            response = planner.poll() if planner else None
            if response:
                brain.publish(thinking=False)
                source = response["request"]
                last_plan_latency = now-source["submitted_at"]
                if "error" in response:
                    raise RuntimeError(response["error"])
                if not response.get("cancelled") and source["revision"] == revision and now-source["submitted_at"] < 28:
                    fresh = client.request("/context", {})
                    if fresh["epoch"] != epoch or fresh["session_id"] != session:
                        break
                    plan = response["plan"]
                    validate_plan(plan, config, fresh)
                    if plan["intent"] is not None:
                        # Preserve planner image yaw; baseline progress at acceptance.
                        basis = dict(source["context"], status=last_status)
                        revision += 1
                        intent = Intent.create(plan, revision, basis, now)
                        supplies_before = {x["name"]:x["count"] for x in last_status.get("supplies",[])}
                        skill = InventorySkill(intent) if intent.data["mode"] in ("craft", "organize") else None
                        blocked_since = None
                    totals["plans"] += 1
                    journal.decision(plan)
                    brain.plan(plan, last_plan_latency*1000)
                    social = {k: v for k,v in plan.items() if k != "intent"}
                    social["action"] = {"tool":"halt","arguments":{}} if plan["intent"] and intent.data["mode"] in ("rest","inspect","craft","organize") else None
                    if plan["intent"] and last_status.get("inventory",{}).get("open") and intent.data["mode"] not in ("craft","organize"):
                        social["action"] = {"tool":"close_inventory","arguments":{}}
                    social_result = client.request("/decision", {"epoch": epoch, "observation_id": fresh["observation_id"], "decision": social})
                    if social.get("speech") and not social_result.get("skipped_speech") and social_result.get("results") and unpack(social_result["results"][-1]).get("ok"):
                        brain.speech(social["speech"]["text"])
                    if plan["intent"]:
                        record("intention: " + intent.data["mode"] + " — " + intent.data["objective"])
                    next_plan = now + plan_interval
                else:
                    record("discarded superseded/expired planner result")
                    next_plan = 0
            evidence = worker.poll()
            if evidence:
                totals["local_results"] += 1
                totals["latencies_ms"].append(round(evidence["seconds"]*1000,2))
                age = time.monotonic() - evidence["captured_at"]
                valid = intent and intent.accepts(evidence, time.monotonic(), epoch, session)
                if shadow:
                    valid = age <= .85
                if valid and not shadow:
                    # Heading and contact speed must describe the body now,
                    # rather than where it was before local inference began.
                    last_status = client.call("get_status")
                    now = time.monotonic()
                    valid = intent.accepts(evidence, now, epoch, session)
                if valid:
                    args, reason = motor.choose(intent, evidence, last_status, now)
                    if args and not shadow:
                        outcome = unpack(client.request("/control/motor", {"epoch": epoch, "arguments": args}))
                        if not outcome.get("ok"):
                            reason = outcome.get("error", "motor rejected")
                        else:
                            totals["actions"] += 1
                            brain.motor(args, reason)
                            totals["capture_to_control_ms"].append(round((time.monotonic()-evidence["captured_at"])*1000,2))
                    if reason in ("uncertain path; reassess", "target lost; reassess", "target location uncertain; reassess", "damage; reassess", "possible water or drop; reassess"):
                        blocked_since = blocked_since or now
                        if not shadow and now-blocked_since >= 2:
                            finish_intent(reason)
                    else:
                        blocked_since = None
                    if args and args["forward"] and last_status.get("locomotion", {}).get("speed_mps", 0) < .2:
                        # Persistent contact is tracked across renewals, not reset per lease.
                        motor.blocked_since = motor.blocked_since or now
                        if not shadow and now-motor.blocked_since > 2:
                            finish_intent("movement stalled; choose a different route")
                    else:
                        motor.blocked_since = None
                else:
                    if intent is None:
                        totals["idle_results"] += 1
                        args, reason = None, "observing while planning"
                    else:
                        totals["stale_results"] += 1
                        args, reason = None, "stale/superseded perception"
                row = {k:v for k,v in evidence.items() if k != "model"}
                row.update(age_ms=round(age*1000,2), controls=args, reason=reason, at=round(now-start,2))
                telemetry.write(json.dumps(row)+"\n"); telemetry.flush()
                brain.perception(evidence["seconds"]*1000, age*1000, reason)
            if not worker.busy and now >= next_capture:
                try:
                    snap = snapshot(client)
                except RuntimeError as exc:
                    if not str(exc).startswith("Fresh player frame unavailable"):
                        raise
                    missing_frame_since = missing_frame_since or time.monotonic()
                    if time.monotonic()-missing_frame_since > 3:
                        raise
                    # A briefly delayed GPU readback is recoverable. No control
                    # is renewed without a new image; the 800 ms lease expires.
                    # Keep checking operator/game health on the normal loop.
                    brain.publish(activity="Waiting for a fresh view")
                    next_capture = time.monotonic()+.1
                    continue
                missing_frame_since = None
                last_snapshot, last_status = snap, snap["status"]
                brain.body(last_status)
                if snap["view"]["frame_id"] == last_frame:
                    stopped.wait(.02)
                    continue
                last_frame = snap["view"]["frame_id"]
                # Target two local decisions/second, without building a backlog.
                # Running inference flat-out starves Valheim on this shared GPU
                # and makes both the game and later decisions dramatically slower.
                next_capture = max(time.monotonic()+.05, now+.5)
                journal.observation(last_status, snap["image"])
                if last_health_value is not None and last_status["health"] < last_health_value and intent and not shadow:
                    finish_intent("health fell; reassess danger")
                last_health_value = last_status["health"]
                if intent and not shadow:
                    if intent.data["mode"] in ("gather","harvest"):
                        gained = [x["name"] for x in last_status.get("supplies",[]) if x["count"]>supplies_before.get(x["name"],0)]
                        if gained:
                            finish_intent("verified inventory gain: " + ", ".join(gained))
                if intent and not shadow:
                    complete = intent.complete(last_status, now)
                    if complete:
                        finish_intent(complete,invalidate=False)
                if skill and intent:
                    operation, event = skill.step(last_status)
                    if event:
                        finish_intent(event)
                    elif operation:
                        fresh = client.request("/context", {})
                        result = client.request("/decision", {"epoch":epoch,"observation_id":fresh["observation_id"],
                            "decision":{"note":"Local inventory sequence","action":operation,"source_event_id":None,"speech":None,"memories":[]}})
                        results = [unpack(r) for r in result["results"]]
                        if results and all(r.get("ok") for r in results):
                            brain.fire(2, ["craft" if intent.data["mode"] == "craft" else "inventory"], operation["tool"])
                        if any(r.get("ok") is False for r in results):
                            finish_intent("inventory step rejected: " + str(results)[:200])
                if shadow and intent is None:
                    data = {"mode":"travel","objective":"shadow travel","target":"","heading":0,"distance":20,"seconds":30,"recipe_id":"","inventory_action":None}
                    intent = Intent.create({"intent":data},revision,dict(context,status=last_status,view=snap["view"]), now)
                if not last_status.get("inventory", {}).get("open"):
                    # Keep observing while Luna thinks, even between intentions.
                    # This also avoids repeatedly making the resident GPU model
                    # cold during planning gaps. No intention means no controls.
                    worker.submit({"png":snap["png"],"frame_id":last_frame,"captured_at":snap["captured_at"],
                        "revision":intent.revision if intent else revision,"epoch":epoch,
                        "target":intent.data["target"] if intent and intent.data["mode"] in ("gather","harvest","combat") else ""})
                plan_due = now >= next_plan
                if intent and now-intent.issued >= .5:
                    remaining = intent.expires-now
                    if intent.data["mode"] == "travel":
                        travelled = last_status.get("locomotion",{}).get("distance_m",0)-intent.start_distance
                        speed = max(2,last_status.get("locomotion",{}).get("speed_mps",0))
                        remaining = min(remaining,max(0,intent.data["distance"]-travelled)/speed)
                    plan_due = plan_due or remaining <= last_plan_latency+2
                if planner and not planner.busy and plan_due:
                    context = client.request("/context", {})
                    if context["epoch"] != epoch or context["session_id"] != session:
                        break
                    active = None if intent is None else dict(intent.data,seconds_remaining=round(max(0,intent.expires-now),1),
                        distance_remaining=round(max(0,intent.data["distance"]-(last_status.get("locomotion",{}).get("distance_m",0)-intent.start_distance)),1))
                    context.update(status=last_status, view=snap["view"], active_intent=active, events=list(events))
                    planner.submit({"context":context,"image":snap["image"],"revision":revision,"submitted_at":time.monotonic()})
                    brain.fire(2, ["plan"], "Considering next intention", thinking=True)
                if max_turns and totals["plans"] >= max_turns:
                    break
            stopped.wait(.01)
        telemetry.close()
        totals["final_status"] = last_status
    except BaseException as exc:
        failure = type(exc).__name__ + ": " + str(exc)[:300]
        raise
    finally:
        stopped.set()
        if brain:
            brain.publish(phase="failed" if failure else "stopped", thinking=False)
        if telemetry:
            telemetry.close()
        try:
            client.request("/control/stop", {})
        except Exception:
            try:
                LocalClient(config,"bridge").request("/control/stop",{},timeout=2)
            except Exception:
                pass
        if worker:
            worker.close()
        if planner:
            planner.close()
        if awake:
            awake.close()
        if journal:
            private_write(journal.path/"dual-summary.json",json.dumps(totals))
            journal.finish(failure)
        for sig,handler in handlers.items():
            signal.signal(sig,handler)
        lock.close()
