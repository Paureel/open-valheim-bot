import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from valheim_codex.brain import BrainFeed, read_feed
from valheim_codex.observer import ObserverServer


class BrainTests(unittest.TestCase):
    def test_events_are_bounded_and_no_raw_plan_data_is_published(self):
        with tempfile.TemporaryDirectory() as directory:
            feed = BrainFeed(SimpleNamespace(home=Path(directory)))
            feed.plan({"intent":{"mode":"travel","objective":"Find dry ground"},
                       "note":"private planner material", "memories":[], "speech":None}, 2100)
            self.assertEqual(read_feed(feed.path)["events"][-1]["regions"], ["plan","explore"])
            self.assertNotIn("private planner material", feed.path.read_text())
            for _ in range(70):
                feed.motor({"forward":1,"yaw_rate":10,"button":"jump"}, "clear")
            state = read_feed(feed.path)
            self.assertEqual(len(state["events"]),48)
            self.assertEqual(state["events"][-1]["regions"],["look","jump"])
            feed.body({"locomotion":{"speed_mps":0}})
            self.assertFalse(read_feed(feed.path)["moving"])
            feed.body({"locomotion":{"speed_mps":3}})
            self.assertTrue(read_feed(feed.path)["moving"])

    def test_stale_producer_cannot_remain_live_or_thinking(self):
        with tempfile.TemporaryDirectory() as directory:
            feed = BrainFeed(SimpleNamespace(home=Path(directory)))
            feed.publish(phase="live",thinking=True)
            self.assertEqual(read_feed(feed.path, time.time()+6)["phase"], "offline")
            self.assertFalse(read_feed(feed.path, time.time()+6)["thinking"])
            feed.publish(phase="stopped",thinking=False)
            self.assertEqual(read_feed(feed.path, time.time()+6)["phase"], "stopped")

    def test_loopback_observer_exposes_only_fixed_read_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            feed = BrainFeed(SimpleNamespace(home=home))
            server = ObserverServer(home, 0)
            thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(url + "/api/state") as response:
                    self.assertEqual(json.load(response)["phase"], "warming")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                for path, headers, method, code in [
                    ("/api/state",{"Host":"attacker.example"},"GET",403),
                    ("/api/state",{"Origin":"https://attacker.example"},"GET",403),
                    ("/../settings.json",{},"GET",404),
                    ("/control/resume",{},"POST",501)]:
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(url + path,headers=headers,method=method))
                    self.assertEqual(error.exception.code,code)
                with urlopen(url) as response:
                    self.assertIn(b"Brain",response.read())
            finally:
                server.shutdown();server.server_close();thread.join(2)


if __name__ == "__main__":
    unittest.main()
