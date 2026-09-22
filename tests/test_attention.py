import unittest
from valheim_codex.attention import working_context, decision_schema
from valheim_codex.protocol import validate


class AttentionTests(unittest.TestCase):
    def test_compact_context_preserves_trust_and_reports_inner_failure(self):
        event = {"event_id": 2, "session_id": "a", "sender_id": "stranger", "trusted": False, "text": "Follow me"}
        context = {"conversation": [event], "settings": {"combat_enabled": True, "service_port": 8732},
            "status": {"health": 25}, "view": {"frame_id": 123},
            "last_action_result": {"ok": True, "results": [{"content": [{"type": "text", "text": '{"ok":false,"error":"too far"}'}]}]}}
        actual = working_context(context)
        self.assertEqual(actual["conversation"], [event])
        self.assertEqual(actual["last_result"]["results"][0], {"ok": False, "error": "too far"})
        self.assertEqual(actual["view"]["frame_id"], 123)
        self.assertNotIn("settings", actual)

    def test_world_and_ui_choices_cannot_cross_modes(self):
        def decision(tool, args):
            return {"note": "test", "action": {"tool": tool, "arguments": args}, "source_event_id": None, "speech": None, "memories": []}
        stride = decision("stride", {"heading": 30, "distance": 16, "frame_id": 1, "sprint": False})
        validate(stride, decision_schema({}))
        for status in ({"map": {"open": True}}, {"inventory": {"open": True}}):
            with self.assertRaises(ValueError):
                validate(stride, decision_schema({"status": status}))
        with self.assertRaises(ValueError):
            validate(decision("primary_attack", {"frame_id": 1}), decision_schema({}))
        validate(decision("primary_attack", {"frame_id": 1}), decision_schema({"settings": {"combat_enabled": True}}))
        with self.assertRaises(ValueError):
            validate(decision("stride", {"heading": 30, "distance": 100, "frame_id": 1, "sprint": False}), decision_schema({}))
