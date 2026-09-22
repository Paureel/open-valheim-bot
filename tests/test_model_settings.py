import tempfile
import unittest

from valheim_codex.codex import AppServer
from valheim_codex.config import Config


class ModelSettingsTests(unittest.TestCase):
    def test_new_and_resumed_threads_select_luna_low(self):
        with tempfile.TemporaryDirectory() as home:
            app = AppServer.__new__(AppServer)
            app.config = Config(home).initialize()
            app.config.settings["character_name"] = "Rowan"
            app.pending = []
            calls = []
            def rpc(method, params):
                calls.append((method, params))
                return {"thread": {"id": "test-thread"}, "model": "gpt-5.6-luna", "reasoningEffort": "low"}
            app.rpc = rpc
            self.assertEqual(app.start_thread(), "test-thread")
            self.assertEqual(app.start_thread("test-thread"), "test-thread")
            self.assertEqual([method for method, _ in calls], ["thread/start", "thread/resume"])
            for _, params in calls:
                self.assertEqual(params["model"], "gpt-5.6-luna")
                self.assertEqual(params["config"]["model_reasoning_effort"], "low")
                self.assertIn('"character_name": "Rowan"', params["developerInstructions"])

    def test_unexpected_model_or_reasoning_fails_closed(self):
        with tempfile.TemporaryDirectory() as home:
            app = AppServer.__new__(AppServer)
            app.config = Config(home).initialize()
            app.pending = []
            for model, effort in [("different-model", "low"), ("gpt-5.6-luna", "medium")]:
                app.rpc = lambda *_: {"thread": {"id": "test-thread"}, "model": model, "reasoningEffort": effort}
                with self.subTest(model=model, effort=effort), self.assertRaises(RuntimeError):
                    app.start_thread("test-thread")
