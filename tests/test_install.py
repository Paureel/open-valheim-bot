import tempfile
import unittest
from pathlib import Path
from valheim_codex.install import install_files, restore


class InstallTests(unittest.TestCase):
    def test_backups_restore_original_and_remove_new_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src, dest = root / "source", root / "game"
            src.mkdir(); dest.mkdir()
            (src / "existing.dll").write_text("new version")
            (src / "added.dll").write_text("added")
            (dest / "existing.dll").write_text("original")
            manifest = install_files(src, dest, root / "backups", "test")
            self.assertEqual((dest / "existing.dll").read_text(), "new version")
            self.assertEqual(restore(manifest), [])
            self.assertEqual((dest / "existing.dll").read_text(), "original")
            self.assertFalse((dest / "added.dll").exists())

    def test_uninstall_preserves_subsequent_user_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src, dest = root / "source", root / "game"
            src.mkdir(); dest.mkdir()
            (src / "settings.txt").write_text("installed")
            manifest = install_files(src, dest, root / "backups", "test")
            (dest / "settings.txt").write_text("user edited")
            self.assertEqual(restore(manifest), [str((dest / "settings.txt").resolve())])
            self.assertEqual((dest / "settings.txt").read_text(), "user edited")

    def test_symlinks_cannot_redirect_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src, dest, outside = root / "source", root / "game", root / "outside"
            src.mkdir(); dest.mkdir(); outside.mkdir()
            (src / "sub").mkdir(); (src / "sub/file").write_text("new")
            (dest / "sub").symlink_to(outside)
            with self.assertRaises(ValueError):
                install_files(src, dest, root / "backups", "test")
            self.assertFalse((outside / "file").exists())
