import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from valheim_codex.supervisor import wait_for_focus

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('binding_check', ROOT / 'scripts/verify-bindings.py')
bindings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bindings)


class PreflightTests(unittest.TestCase):
    def test_missing_bridge_does_not_wait_or_start_anything(self):
        client = Mock()
        client.call.return_value = {'bridge': {'ready': False, 'reason': 'Bridge unreachable'}}
        stop = Mock()
        wait_for_focus(client, stop)
        stop.wait.assert_not_called()
        client.call.assert_called_once_with('health')

    def test_focus_wait_ends_before_gameplay(self):
        client = Mock()
        client.call.side_effect = [
            {'bridge': {'reason': 'Game is not focused'}},
            {'bridge': {'ready': True, 'reason': None}},
        ]
        stop = Mock()
        stop.wait.return_value = False
        with patch('builtins.print'):
            wait_for_focus(client, stop)
        self.assertEqual(client.call.call_count, 2)
        client.request.assert_not_called()

    def test_cancel_during_focus_wait(self):
        client = Mock()
        client.call.return_value = {'bridge': {'reason': 'Game is not focused'}}
        stop = threading.Event()
        stop.set()
        with patch('builtins.print'):
            wait_for_focus(client, stop)
        client.call.assert_called_once_with('health')

    def test_changed_assembly_is_rejected(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'game.dll'
            target.write_bytes(b'reviewed fixture')
            reviewed = {'game.dll': hashlib.sha256(target.read_bytes()).hexdigest()}
            bindings.verify_hashes(Path(directory), reviewed)
            target.write_bytes(b'updated fixture')
            with self.assertRaisesRegex(ValueError, 'Unreviewed assembly'):
                bindings.verify_hashes(Path(directory), reviewed)
