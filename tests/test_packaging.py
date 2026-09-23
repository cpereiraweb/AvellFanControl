import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('migration',ROOT/'packaging/migrate_legacy.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MigrationTests(unittest.TestCase):
    def test_archive_preserves_contents_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'usr/local/libexec/avell-fan';p.parent.mkdir(parents=True);p.write_text('helper')
            module=root/'lib/modules/test/updates/avell-thermal/avell_profiles.ko';module.parent.mkdir(parents=True);module.write_bytes(b'module')
            migration=m.Migration(root,check_owner=False)
            self.assertEqual(migration.archive(),2)
            self.assertFalse(p.exists());self.assertFalse(module.exists())
            self.assertEqual((migration.backup/'usr/local/libexec/avell-fan').read_text(),'helper')
            manifest=json.loads((migration.backup/'manifest.json').read_text())
            self.assertEqual(len(manifest),2)
            self.assertEqual(migration.archive(),0)
    def test_custom_configuration_prevents_any_removal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'usr/local/libexec/avell-fan';p.parent.mkdir(parents=True);p.write_text('helper')
            conf=root/'etc/modules-load.d/avell-thermal.conf';conf.parent.mkdir(parents=True);conf.write_text('another_module\n')
            with self.assertRaises(RuntimeError):m.Migration(root,check_owner=False).archive()
            self.assertTrue(p.exists());self.assertTrue(conf.exists())
    def test_symlink_is_never_followed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'usr/local/libexec/avell-fan';p.parent.mkdir(parents=True);p.symlink_to('/etc/passwd')
            with self.assertRaises(RuntimeError):m.Migration(root,check_owner=False).archive()
            self.assertTrue(p.is_symlink())
    def test_different_backup_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'usr/local/libexec/avell-fan';p.parent.mkdir(parents=True);p.write_text('old')
            migration=m.Migration(root,check_owner=False);migration.archive();p.write_text('changed')
            with self.assertRaises(RuntimeError):migration.archive()
            self.assertEqual(p.read_text(),'changed')
