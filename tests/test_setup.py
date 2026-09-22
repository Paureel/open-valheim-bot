import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from valheim_codex import setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="valheim setup ")
        self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(setup, "ROOT", self.root)
        self.patch.start()
        self.game = self.root / "Steam library/Valheim"
        managed = self.game / "valheim.app/Contents/Resources/Data/Managed"
        managed.mkdir(parents=True)
        (managed / "game.dll").write_bytes(b"reviewed game")
        (self.root / "bridge/Plugin").mkdir(parents=True)
        (self.root / "bridge/Plugin/reviewed-assemblies.json").write_text(json.dumps({
            "game.dll": hashlib.sha256(b"reviewed game").hexdigest()}))

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def arguments(self, **values):
        return SimpleNamespace(**dict(dict(step="prepare", python=None, dry_run=False,
                                          normal_play_verified=True), **values))

    def archive(self, names):
        path = self.root / "loader.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name, data in names:
                z.writestr(name, data)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_hash_mismatch_stops_before_dependencies_or_configuration_change(self):
        (self.game / "valheim.app/Contents/Resources/Data/Managed/game.dll").write_bytes(b"new game update")
        with patch.object(setup, "stage_bepinex") as stage, patch.object(setup, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Unsupported game files"):
                setup.prepare(self.arguments(), self.game)
            stage.assert_not_called()
            run.assert_not_called()

    def test_dry_run_performs_no_writes_downloads_or_child_installs(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        with patch.object(setup, "native_python", return_value="/native/python3.12"), \
             patch.object(setup.shutil, "which", return_value="/bin/codex"), \
             patch.object(setup, "stage_bepinex") as stage, \
             patch.object(setup.subprocess, "run") as child:
            setup.prepare(self.arguments(dry_run=True), self.game)
            stage.assert_not_called()
            child.assert_not_called()
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))

    def test_prepare_does_not_install_game_files_or_register_mcp(self):
        (self.root / ".tools").mkdir()
        with patch.object(setup, "native_python", return_value="/native/python3.12"), \
             patch.object(setup.shutil, "which", return_value="/bin/codex"), \
             patch.object(setup, "stage_bepinex"), patch.object(setup, "run") as commands:
            setup.prepare(self.arguments(), self.game)
        calls = [[str(x) for x in call.args[0]] for call in commands.call_args_list]
        self.assertFalse(any("install-game-files.py" in part for cmd in calls for part in cmd))
        local = next(cmd for cmd in calls if any(part.endswith("install-local.py") for part in cmd))
        self.assertIn("--no-mcp", local)
        self.assertEqual((self.root / ".tools/game-dir").read_text().strip(), str(self.game))

    def test_archive_integrity_and_escape_paths_are_rejected(self):
        for name in ["../outside", "/tmp/escape", "folder/../../outside", "folder\\outside"]:
            path, digest = self.archive([(name, b"bad")])
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                setup.checked_archive(path, "0" * 64)
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                setup.checked_archive(path, digest)
        self.assertFalse((self.root.parent / "outside").exists())

    def test_archive_symlink_is_rejected(self):
        link = zipfile.ZipInfo("loader/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        path, digest = self.archive([(link, b"/outside")])
        with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
            setup.checked_archive(path, digest)

    def test_cached_loader_is_verified_and_staging_is_repeatable(self):
        path, digest = self.archive([("BepInExPack_Valheim/BepInEx/core/BepInEx.dll", b"loader")])
        (self.root / ".tools").mkdir()
        path.rename(self.root / ".tools" / ("BepInExPack_Valheim-" + setup.BEPINEX_VERSION + ".zip"))
        with patch.object(setup, "BEPINEX_SHA256", digest), patch.object(setup.subprocess, "run") as network:
            setup.stage_bepinex()
            setup.stage_bepinex()
            network.assert_not_called()
            staged = self.root / ".tools/bepinex-staged/BepInExPack_Valheim/BepInEx/core/BepInEx.dll"
            staged.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "differs"):
                setup.stage_bepinex()
            self.assertEqual(staged.read_bytes(), b"changed")

    def test_invalid_download_is_not_promoted_or_extracted(self):
        def download(command, **_):
            Path(command[-1]).write_bytes(b"not the expected archive")
        with patch.object(setup.subprocess, "run", side_effect=download):
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                setup.stage_bepinex()
        self.assertEqual(list((self.root / ".tools").iterdir()), [])

    def test_install_refuses_running_game_before_any_mutation(self):
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
             patch.object(setup, "stage_bepinex") as stage, patch.object(setup, "run") as commands:
            with self.assertRaisesRegex(RuntimeError, "Quit Valheim"):
                setup.install_stage(self.arguments(step="loader"), self.game)
            stage.assert_not_called()
            commands.assert_not_called()

    def test_process_check_failure_does_not_allow_install(self):
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=2)):
            with self.assertRaisesRegex(RuntimeError, "Could not check"):
                setup.require_game_closed()

    def test_saved_game_and_explicit_override_handle_spaces(self):
        (self.root / ".tools").mkdir()
        (self.root / ".tools/game-dir").write_text(str(self.game) + "\n")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(setup.game_path(), self.game)
            self.assertEqual(setup.game_path(str(self.root / "Other library/Valheim")), self.root / "Other library/Valheim")

    def test_rosetta_python_is_not_accepted_for_mlx(self):
        candidate = self.root / "python3.12"
        candidate.touch()
        with patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, "Native arm64 Python 3.12"):
                setup.native_python(str(candidate))

    def test_command_paths_are_arguments_never_shell_code(self):
        argument = self.root / "space ' quote $(not-a-command)"
        with patch.object(setup.subprocess, "run") as run:
            setup.run(["python3", argument])
        self.assertEqual(run.call_args.args[0], ["python3", str(argument)])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_manual_play_confirmation_required_without_interactive_input(self):
        with patch.object(setup, "require_game_closed"), \
             patch.object(setup.sys.stdin, "isatty", return_value=False), \
             patch.object(setup, "run") as commands:
            with self.assertRaisesRegex(RuntimeError, "Join normally"):
                setup.install_stage(self.arguments(step="bridge", normal_play_verified=False), self.game)
            commands.assert_not_called()
