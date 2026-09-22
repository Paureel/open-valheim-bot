"""Real C# HTTP -> Python gateway -> MCP + restart tests, with a simulated game only."""
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from valheim_codex.config import Config, ROOT, private_write
from valheim_codex.protocol import LocalClient
from valheim_codex.service import LocalServer, Service
from valheim_codex.supervisor import run
from valheim_codex.codex import AppServer


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = Config(cls.tmp.name).initialize()
        settings = dict(cfg.settings, world_id="simulation", character_name="Codex", bridge_port=free_port(), service_port=free_port())
        private_write(cfg.home / "settings.json", json.dumps(settings))
        private_write(cfg.home / "trusted-players.json", json.dumps({"owners": ["simulation-owner-id"], "trusted_players": []}))
        cls.cfg = Config(cls.tmp.name)
        cls.proc = subprocess.Popen([str(ROOT / ".tools/dotnet/dotnet"), str(ROOT / "bridge/Harness/bin/Release/net10.0/ValheimCodexBridge.Harness.dll"),
            "--serve", "--port", str(settings["bridge_port"]), "--token-file", str(cfg.home / "bridge.token")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        cls.bridge = LocalClient(cls.cfg, "bridge")
        for _ in range(80):
            try:
                cls.bridge.request("/health", timeout=0.2)
                break
            except Exception:
                if cls.proc.poll() is not None:
                    raise RuntimeError(cls.proc.communicate()[1])
                time.sleep(0.05)
        else:
            cls.proc.terminate(); raise RuntimeError("Simulation bridge did not start")
        cls.service = Service(cls.cfg)
        cls.server = LocalServer(cls.service)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.service.start_polling()
        cls.client = LocalClient(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
        cls.service.close()
        cls.proc.terminate(); cls.proc.communicate(timeout=5)
        cls.tmp.cleanup()

    def test_mcp_initialize_tools_image_and_leased_movement(self):
        result = self.client.request("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(result["result"]["serverInfo"]["name"], "valheim-codex")
        result = self.client.request("/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in result["result"]["tools"]}
        self.assertIn("remember_location", names)
        self.assertNotIn("run_command", names)
        self.client.request("/control/resume", {})
        time.sleep(0.04)
        image = self.client.call("observe_player_view")
        self.assertEqual(image["content"][0]["type"], "image")
        self.client.call("move", {"forward": 1, "strafe": 0, "duration_ms": 100})
        time.sleep(0.2)
        self.assertFalse(self.bridge.request("/health")["held"])
        self.client.call("stop")
        time.sleep(0.04)
        self.assertTrue(self.bridge.request("/health")["paused"])

    def test_auth_origin_and_removed_console_endpoints(self):
        for target in ("bridge", "service"):
            port = self.cfg.settings[target + "_port"]
            with self.subTest(target=target):
                request = urllib.request.Request("http://127.0.0.1:" + str(port) + "/health")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 401)
                request.add_header("Authorization", "Bearer " + self.cfg.token(target))
                request.add_header("Origin", "https://untrusted.example")
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 403)
        with self.assertRaises(RuntimeError) as error:
            self.bridge.request("/command", {"text": "spawn Troll"})
        self.assertIn("unknown route", str(error.exception))

    def test_travel_heartbeat_requires_current_resume_epoch(self):
        self.client.request("/control/resume", {})
        epoch=self.client.request("/context", {})["epoch"]
        self.assertTrue(self.client.request("/control/travel-heartbeat", {"epoch":epoch})["ok"])
        self.client.request("/control/stop", {})
        self.assertFalse(self.client.request("/control/travel-heartbeat", {"epoch":epoch})["ok"])
        self.client.request("/control/resume", {})
        self.assertFalse(self.client.request("/control/travel-heartbeat", {"epoch":epoch})["ok"])
        self.client.request("/control/stop", {})

    def test_motor_result_requires_current_epoch_and_expires_without_worker(self):
        from valheim_codex.motor import controls
        from valheim_codex.protocol import unpack
        self.client.request("/control/resume", {})
        epoch=self.client.request("/context", {})["epoch"]
        payload={"epoch":epoch,"arguments":controls(1,forward=1,duration_ms=200)}
        self.assertTrue(unpack(self.client.request("/control/motor",payload))["ok"])
        time.sleep(.3)
        self.assertFalse(self.bridge.request("/health")["held"])
        self.client.request("/control/stop", {})
        self.client.request("/control/resume", {})
        with self.assertRaises(RuntimeError):
            self.client.request("/control/motor",payload)
        self.client.request("/control/stop", {})

    def test_real_csharp_chat_and_memory_roundtrip(self):
        chat = self.client.call("get_chat", {"after_event_id": 0, "limit": 10})
        self.assertEqual(chat["events"][0]["text"], "Codex, turn around.")
        self.client.call("remember_location", {"name": "Test base", "description": "A visual landmark", "confidence": 1, "source": "simulation only"})
        result = self.client.call("find_location", {"query": "Test base"})
        self.assertEqual(result[0]["subject"], "Test base")

    def test_dual_loop_keeps_renewing_during_slow_planning(self):
        from valheim_codex.dual_supervisor import run as run_dual, snapshot
        from unittest.mock import patch
        class LocalVision:
            identity={"model":"simulation only"}
            def __init__(self,config):self.busy=False;self.pending=None
            def submit(self,request):self.busy=True;self.pending=request
            def poll(self):
                if not self.pending:return None
                r=self.pending;self.pending=None;self.busy=False
                return {k:r[k] for k in ("frame_id","captured_at","revision","epoch")} | {"seconds":.01,"support":[.95,.4,.4,.1,.1,.1]}
            def close(self):pass
        class SlowPlanner:
            pending_during_actions=False
            def __init__(self,config,stopped):self.busy=False;self.pending=None;self.count=0
            def submit(self,request):
                self.pending=request;self.busy=True;self.count+=1
                self.due=time.monotonic()+(.02 if self.count==1 else 5)
            def poll(self):
                if not self.pending or time.monotonic()<self.due:return None
                r=self.pending;self.pending=None;self.busy=False
                return {"request":r,"plan":{"note":"simulation travel","source_event_id":None,"speech":None,"memories":[],
                    "intent":{"mode":"travel","objective":"cross the clearing","target":"","heading":0,"distance":20,
                              "seconds":30,"recipe_id":"","inventory_action":None}}}
            def close(self):SlowPlanner.pending_during_actions=self.busy and self.count==2
        captures = 0
        def delayed_capture(client):
            nonlocal captures
            captures += 1
            if captures == 3:
                raise RuntimeError("Fresh player frame unavailable; wait for a focused game frame")
            return snapshot(client)
        with patch("valheim_codex.dual_supervisor.snapshot", side_effect=delayed_capture):
            run_dual(self.cfg,seconds=4,worker_factory=LocalVision,planner_factory=SlowPlanner,plan_interval=.3)
        newest=max((self.cfg.home/"playtests").iterdir(),key=lambda p:p.name)
        summary=json.loads((newest/"dual-summary.json").read_text())
        self.assertTrue(SlowPlanner.pending_during_actions)
        self.assertGreaterEqual(summary["actions"],4)
        self.assertEqual(summary["stale_results"],0)
        brain=json.loads((self.cfg.home/"run/brain.json").read_text())
        self.assertEqual(brain["phase"],"stopped")
        # This harness accepts inputs but has no measured body velocity. The
        # observer must not turn accepted movement into a claim of actual motion.
        self.assertFalse(brain["moving"])
        self.assertFalse(any("move" in e["regions"] for e in brain["events"]))
        self.assertTrue(any("see" in e["regions"] for e in brain["events"]))
        self.assertTrue(self.service.paused)
        time.sleep(.05)
        self.assertFalse(self.bridge.request("/health")["held"])

    def test_supervisor_one_turn_and_resume_with_scripted_model(self):
        class ScriptedModel:
            resumed = []
            def __init__(self, config): pass
            def start_thread(self, previous):
                self.resumed.append(previous)
                return "scripted-simulation-thread"
            def decide(self, context, image, should_stop):
                self.assert_image = image["content"][0]["type"] == "image"
                return {"note": "Simulation turns around", "action": {"tool": "look", "arguments": {"delta_yaw": 180, "delta_pitch": 0}}, "source_event_id": 1, "speech": None, "memories": []}
            def close(self): pass
        saved = list((self.cfg.home / "run").glob("session-*.json"))
        previous = json.loads(saved[0].read_text())["thread_id"] if saved else None
        existing = set((self.cfg.home / "playtests").glob("*/summary.json")) if (self.cfg.home / "playtests").exists() else set()
        run(self.cfg, max_turns=1, app_factory=ScriptedModel)
        run(self.cfg, max_turns=1, app_factory=ScriptedModel)
        self.assertEqual(ScriptedModel.resumed, [previous, "scripted-simulation-thread"])
        self.assertTrue(self.service.paused)
        journals = set((self.cfg.home / "playtests").glob("*/summary.json")) - existing
        self.assertEqual(len(journals), 2)
        for summary in journals:
            self.assertEqual(json.loads(summary.read_text())["observations"], 1)
            self.assertTrue((summary.parent / "0001.png").exists())
            self.assertTrue((summary.parent / "0001-decision.json").exists())
            self.assertTrue((summary.parent / "0001-result.json").exists())
            self.assertEqual((summary.parent / "0001.png").stat().st_mode & 0o777, 0o600)

    def test_slow_model_decision_is_discarded_before_gameplay(self):
        previous_age = self.cfg.settings["max_observation_age_seconds"]
        self.cfg.settings["max_observation_age_seconds"] = 0.2
        class SlowFirstModel:
            turns = 0
            def __init__(self, config): pass
            def start_thread(self, previous): return "scripted-slow-thread"
            def decide(self, context, image, should_stop):
                self.turns += 1
                if self.turns == 1:
                    time.sleep(0.3)
                return {"note": "slow observation test", "action": {"tool": "look", "arguments": {"delta_yaw": 1, "delta_pitch": 0}}, "source_event_id": None, "speech": None, "memories": []}
            def close(self): pass
        try:
            run(self.cfg, max_turns=2, app_factory=SlowFirstModel)
            newest = max((self.cfg.home / "playtests").iterdir(), key=lambda p: p.name)
            rejected = json.loads((newest / "0001-result.json").read_text())["result"]
            accepted = json.loads((newest / "0002-result.json").read_text())["result"]
            self.assertFalse(rejected["ok"])
            self.assertIn("discarded", rejected["error"])
            self.assertTrue(accepted["ok"])
            self.assertTrue(self.service.paused)
        finally:
            self.cfg.settings["max_observation_age_seconds"] = previous_age

    def test_stdio_codex_transport(self):
        request = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}) + "\n"
        result = subprocess.run([str(ROOT / "scripts/valheim-codex"), "--home", str(self.cfg.home), "stdio"],
            input=request, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertEqual(response["id"], 7)
        self.assertTrue(response["result"]["tools"])

    def test_visual_windows_keep_recent_progress_and_persistent_goals(self):
        class WindowModel(AppServer):
            windows = []
            seen = []
            def __init__(self, config):
                self.last_usage = {"inputTokens": 1000}
            def start_thread(self, previous=None):
                self.windows.append(previous)
                return previous or "window-" + str(len(self.windows))
            def decide(self, context, image, should_stop):
                self.seen.append(context)
                return {"note": "Continue gathering", "action": None, "source_event_id": None, "speech": None, "memories": []}
            def close(self): pass
        prior = self.cfg.settings["decision_interval_seconds"]
        self.cfg.settings["decision_interval_seconds"] = .01
        try:
            self.service.memory.goal("window-food", "Find food", "active", "test evidence")
            run(self.cfg, max_turns=9, app_factory=WindowModel)
            self.assertGreaterEqual(len(WindowModel.windows), 2)
            self.assertIsNone(WindowModel.windows[-1])
            self.assertTrue(WindowModel.seen[-1]["progress"]["recent_actions"])
            self.assertIn("window-food", [g["goal_id"] for g in WindowModel.seen[-1]["goals"]])
            state = json.loads(next((self.cfg.home / "run").glob("session-*.json")).read_text())
            self.assertLess(state["window_turns"], 8)
            self.assertEqual(state["recent_actions"][-1]["note"], "Continue gathering")
        finally:
            self.cfg.settings["decision_interval_seconds"] = prior

    def test_stop_during_model_preparation_is_not_overridden(self):
        client = self.client
        class StoppedModel:
            def __init__(self, config): pass
            def start_thread(self, previous):
                client.request("/control/stop", {})
                return "interrupted-start"
            def decide(self, *args):
                raise AssertionError("Stopped preparation must not reach model decisions")
            def close(self): pass
        with self.assertRaises(InterruptedError):
            run(self.cfg, max_turns=1, app_factory=StoppedModel)
        self.assertTrue(self.service.paused)

    def test_unavailable_saved_working_session_keeps_recent_context(self):
        import hashlib
        key=hashlib.sha256(self.cfg.settings['world_id'].encode()).hexdigest()[:16]
        session=self.cfg.home/'run'/('session-'+key+'.json')
        private_write(session,json.dumps({'thread_id':'unavailable-window','bounded_context':True,'compact_context':True,'window_turns':0,
            'recent_actions':[{'note':'Rest before continuing','action':None,'result':{'ok':True}}]}))
        class ResumeRejected(AppServer):
            starts=[]
            seen=[]
            def __init__(self,config):self.last_usage={}
            def start_thread(self,previous=None):
                self.starts.append(previous)
                if previous:raise RuntimeError('Codex thread/resume failed: -32600')
                return 'replacement-window'
            def decide(self,context,image,should_stop):
                self.seen.append(context)
                return {'note':'Resting','action':None,'source_event_id':None,'speech':None,'memories':[]}
            def close(self):pass
        run(self.cfg,max_turns=1,app_factory=ResumeRejected)
        self.assertEqual(ResumeRejected.starts,['unavailable-window',None])
        self.assertEqual(ResumeRejected.seen[0]['progress']['recent_actions'][0]['note'],'Rest before continuing')
        self.assertEqual(json.loads(session.read_text())['thread_id'],'replacement-window')
        self.assertTrue(self.service.paused)
