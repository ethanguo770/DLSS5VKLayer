#!/usr/bin/env python3
"""Regression checks for portable registration; needs no GPU or model DLL."""

import ctypes.util
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


class ModelPackagingTests(unittest.TestCase):
    def test_flat_and_rtx40_profiles_keep_distinct_files_and_hashes(self):
        spec = importlib.util.spec_from_file_location('bundle_builder', REPO / 'packaging/make-ubuntu-bundle.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, output = base / 'source', base / 'output'
            (source / 'rtx40').mkdir(parents=True)
            (source / 'test-only').mkdir()
            (source / 'nvngx_dlssnr.dll').write_bytes(b'universal model')
            (source / 'rtx40/nvngx_dlssnr.dll').write_bytes(b'Ada candidate')
            (source / 'test-only/ngx_mock.dll').write_bytes(b'not a production profile')
            records = builder.copy_models(source, output)
            self.assertEqual(set(records), {'nvngx_dlssnr.dll', 'rtx40/nvngx_dlssnr.dll'})
            for relative, payload in [('nvngx_dlssnr.dll', b'universal model'),
                                      ('rtx40/nvngx_dlssnr.dll', b'Ada candidate')]:
                self.assertEqual((output / relative).read_bytes(), payload)
                self.assertEqual(records[relative], {'size': len(payload),
                                  'sha256': hashlib.sha256(payload).hexdigest()})
            self.assertFalse((output / 'test-only').exists())
            (source / 'rtx40/nvngx_dlssnr.dll').unlink()
            with self.assertRaisesRegex(RuntimeError, 'RTX 40 profile'):
                builder.copy_models(source, base / 'incomplete')
            (source / 'rtx40').rmdir()
            self.assertEqual(set(builder.copy_models(source, base / 'flat')), {'nvngx_dlssnr.dll'})


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dlssnr-registration-')
        self.base = Path(self.temporary.name)
        self.bundle = self.base / 'package with spaces'
        (self.bundle / 'layer').mkdir(parents=True)
        (self.bundle / 'layer/libVkLayer_NV_dlssnr.so').write_bytes(b'current layer')
        (self.bundle / 'layer32').mkdir(parents=True)
        (self.bundle / 'layer32/libVkLayer_NV_dlssnr.so').write_bytes(b'current 32-bit layer')
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
        self.target32 = self.manifests / 'dlssnr-portable-32.json'

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

    def assert_portable_manifest_shape(self, target, name, bits):
        keys = list(json.loads(target.read_text(), object_pairs_hook=dict).keys())
        self.assertEqual(keys[-1], 'layer')
        self.assertLess(keys.index('dlssnr_portable_manifest'), keys.index('layer'))
        manifest = json.loads(target.read_text())
        self.assertEqual(manifest['dlssnr_portable_manifest'], 1)
        self.assertEqual(manifest['layer']['name'], name)
        self.assertEqual(manifest['layer']['library_arch'], bits)

    def test_register_repeat_and_move(self):
        self.launch()
        self.assert_portable_manifest_shape(self.target, 'VK_LAYER_NV_dlssnr', '64')
        self.assert_portable_manifest_shape(self.target32, 'VK_LAYER_NV_dlssnr_32', '32')
        first = self.target.read_bytes()
        first32 = self.target32.read_bytes()
        self.launch()
        self.assertEqual(self.target.read_bytes(), first)
        self.assertEqual(self.target32.read_bytes(), first32)
        moved = self.base / 'moved package'
        self.bundle.rename(moved)
        self.bundle = moved
        self.launch()
        manifest = json.loads(self.target.read_text())
        self.assertEqual(manifest['layer']['library_path'],
                         str(moved / 'layer/libVkLayer_NV_dlssnr.so'))
        manifest32 = json.loads(self.target32.read_text())
        self.assertEqual(manifest32['layer']['library_path'],
                         str(moved / 'layer32/libVkLayer_NV_dlssnr.so'))
        self.assert_portable_manifest_shape(self.target, 'VK_LAYER_NV_dlssnr', '64')
        self.assert_portable_manifest_shape(self.target32, 'VK_LAYER_NV_dlssnr_32', '32')
        self.assertFalse((self.base / 'config/environment.d').exists())

    def test_owned_manifest_with_old_marker_order_is_repaired(self):
        self.launch()
        previous = json.loads(self.target.read_text())
        old_order = {'file_format_version': previous['file_format_version'],
                     'layer': previous['layer'],
                     'dlssnr_portable_manifest': 1}
        self.target.write_text(json.dumps(old_order, indent=2) + '\n')
        self.assertEqual(list(json.loads(self.target.read_text(),
                                         object_pairs_hook=dict).keys())[-1],
                         'dlssnr_portable_manifest')
        self.launch()
        self.assert_portable_manifest_shape(self.target, 'VK_LAYER_NV_dlssnr', '64')

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

    def test_real_vulkan_loader_enumerates_fixed_manifest(self):
        if ctypes.util.find_library('vulkan') is None:
            self.skipTest('libvulkan.so.1 is not installed')
        real_layer = REPO / 'build/native/layer_linux/libVkLayer_NV_dlssnr.so'
        if not real_layer.is_file():
            self.skipTest('native Vulkan layer is not built')
        self.launch()
        fixed = json.loads(self.target.read_text())
        fixed['layer']['library_path'] = str(real_layer)
        self.target.write_text(json.dumps(fixed, indent=2) + '\n')
        old = {'file_format_version': fixed['file_format_version'],
               'layer': fixed['layer'],
               'dlssnr_portable_manifest': 1}
        old_folder = self.base / 'old-order'
        old_folder.mkdir()
        (old_folder / 'dlssnr-old.json').write_text(json.dumps(old, indent=2) + '\n')

        old_result = self.vulkan_layers(old_folder)
        # The old shape is a negative control on affected loaders, but a future
        # loader fixing its parser must not make this regression test fail.
        if 'VK_LAYER_NV_dlssnr' not in old_result['layers']:
            self.assertIn("Multiple 'layer'", old_result['stderr'])

        fixed_result = self.vulkan_layers(self.manifests)
        self.assertIn('VK_LAYER_NV_dlssnr', fixed_result['layers'])

    def vulkan_layers(self, manifest_directory):
        probe = r'''
import ctypes
import json

class Layer(ctypes.Structure):
    _fields_ = [('name', ctypes.c_char * 256), ('spec', ctypes.c_uint32),
                ('implementation', ctypes.c_uint32), ('description', ctypes.c_char * 256)]

vk = ctypes.CDLL('libvulkan.so.1')
enumerate_layers = vk.vkEnumerateInstanceLayerProperties
enumerate_layers.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(Layer)]
enumerate_layers.restype = ctypes.c_int32
count = ctypes.c_uint32()
result = enumerate_layers(ctypes.byref(count), None)
assert result == 0, result
layers = (Layer * count.value)()
result = enumerate_layers(ctypes.byref(count), layers)
assert result == 0, result
print(json.dumps([layer.name.decode() for layer in layers[:count.value]]))
'''
        env = dict(os.environ, HOME=str(self.base / 'probe-home'),
                   XDG_CONFIG_HOME=str(self.base / 'probe-config'),
                   XDG_DATA_HOME=str(self.base / 'probe-data'),
                   XDG_CONFIG_DIRS=str(self.base / 'probe-system-config'),
                   XDG_DATA_DIRS=str(self.base / 'probe-system-data'),
                   VK_LAYER_PATH=str(manifest_directory),
                   VK_LOADER_DEBUG='error,warn,layer', VKLayer_DLSS5='1')
        result = subprocess.run([sys.executable, '-c', probe], env=env,
                                text=True, errors='replace', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=20, check=True)
        return {'layers': json.loads(result.stdout.strip().splitlines()[-1]),
                'stderr': result.stderr}


if __name__ == '__main__':
    unittest.main()
