#!/usr/bin/env python3
"""Regression checks for portable registration; needs no GPU or model DLL."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parent.parent


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dlssnr-registration-')
        self.base = Path(self.temporary.name)
        self.bundle = self.base / 'package with spaces'
        (self.bundle / 'layer').mkdir(parents=True)
        (self.bundle / 'layer/libVkLayer_NV_dlssnr.so').write_bytes(b'current layer')
        shutil.copyfile(REPO / 'layer_linux/manifest/VK_LAYER_NV_dlssnr.json',
                        self.bundle / 'layer/manifest.json')
        (self.bundle / 'start-dlssnr.sh').write_text(
            (REPO / 'packaging/ubuntu-bundle-launch.sh').read_text())
        self.env = dict(os.environ, HOME=str(self.base / 'home'),
                        XDG_DATA_HOME=str(self.base / 'data'),
                        XDG_CONFIG_HOME=str(self.base / 'config'),
                        XDG_DATA_DIRS=str(self.base / 'system-data'),
                        XDG_CONFIG_DIRS=str(self.base / 'system-config'))
        self.manifests = self.base / 'data/vulkan/implicit_layer.d'
        self.manifests.mkdir(parents=True)
        self.target = self.manifests / 'dlssnr-portable-64.json'

    def tearDown(self):
        self.temporary.cleanup()

    def launch(self, success=True):
        result = subprocess.run(['bash', str(self.bundle / 'start-dlssnr.sh'),
                                 '--register-layer-only'], env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def existing(self, library):
        file = self.manifests / 'existing.json'
        file.write_text(json.dumps({'layer': {'name': 'VK_LAYER_NV_dlssnr',
                                             'library_path': str(library)}}))
        return file

    def test_register_repeat_and_move(self):
        self.launch()
        first = self.target.read_bytes()
        self.launch()
        self.assertEqual(self.target.read_bytes(), first)
        moved = self.base / 'moved package'
        self.bundle.rename(moved)
        self.bundle = moved
        self.launch()
        manifest = json.loads(self.target.read_text())
        self.assertEqual(manifest['layer']['library_path'],
                         str(moved / 'layer/libVkLayer_NV_dlssnr.so'))
        self.assertFalse((self.base / 'config/environment.d').exists())

    def test_matching_existing_layer_is_reused(self):
        self.existing(self.bundle / 'layer/libVkLayer_NV_dlssnr.so')
        self.launch()
        self.assertFalse(self.target.exists())

    def test_different_existing_layer_is_preserved_and_rejected(self):
        old = self.base / 'old-layer.so'
        old.write_bytes(b'old layer')
        registration = self.existing(old)
        original = registration.read_bytes()
        result = self.launch(success=False)
        self.assertIn('differs from this package', result.stderr)
        self.assertEqual(registration.read_bytes(), original)
        self.assertFalse(self.target.exists())

    def test_missing_registered_library_is_rejected(self):
        self.existing(self.base / 'missing.so')
        self.launch(success=False)
        self.assertFalse(self.target.exists())

    def test_duplicate_installation_is_preserved_and_rejected(self):
        self.launch()
        before = self.target.read_bytes()
        self.existing(self.bundle / 'layer/libVkLayer_NV_dlssnr.so')
        result = self.launch(success=False)
        self.assertIn('Duplicate', result.stderr)
        self.assertEqual(self.target.read_bytes(), before)

    def test_unrelated_target_is_not_overwritten(self):
        self.target.write_text('{"owned_by": "someone else"}')
        original = self.target.read_bytes()
        self.launch(success=False)
        self.assertEqual(self.target.read_bytes(), original)

    def test_symlink_target_is_not_overwritten(self):
        other = self.base / 'other.json'
        other.write_text('{}')
        self.target.symlink_to(other)
        self.launch(success=False)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(other.read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
