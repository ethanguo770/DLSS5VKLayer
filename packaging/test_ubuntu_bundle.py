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
from types import SimpleNamespace
import unittest
from unittest import mock


sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parent.parent


def load_builder():
    spec = importlib.util.spec_from_file_location('bundle_builder', REPO / 'packaging/make-ubuntu-bundle.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


class BundlePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dlssnr-publication-')
        self.base = Path(self.temporary.name)
        self.output = self.base / 'dist'
        self.output.mkdir()
        self.builder = load_builder()
        self.args = SimpleNamespace(output_dir=self.output, name='dlssnr-ubuntu22.04-x86_64')
        self.destination = self.output / self.args.name
        self.archive = self.output / (self.args.name + '.tar.gz')
        self.checksum = self.output / (self.args.name + '.tar.gz.sha256')

    def tearDown(self):
        self.temporary.cleanup()

    def make_bundle(self, root, payload):
        for relative in ['DLSSNR', 'helper/dlssnr_helper.exe', 'layer/libVkLayer_NV_dlssnr.so']:
            file = root / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(payload)
        (root / 'bundle-metadata.json').write_text(json.dumps({
            'target': 'Ubuntu 22.04 x86_64', 'wine_version': self.builder.WINE_VERSION,
            'runtime_dll_pins': {'DXVK_VERSION': 'test', 'DXVK_NVAPI_VERSION': 'test'}}))

    def package(self, payload=b'new'):
        with mock.patch.object(self.builder, 'build',
                               side_effect=lambda args, repo, root: self.make_bundle(root, payload)):
            return self.builder.package(self.args, REPO)

    def snapshot(self):
        return {file.relative_to(self.output).as_posix(): file.read_bytes()
                for file in self.output.rglob('*') if file.is_file()}

    def test_repeated_build_replaces_directory_archive_and_checksum(self):
        self.package(b'old')
        (self.destination / 'obsolete.txt').write_bytes(b'remove with old package')
        self.package(b'new')
        self.assertEqual((self.destination / 'DLSSNR').read_bytes(), b'new')
        self.assertFalse((self.destination / 'obsolete.txt').exists())
        with self.builder.tarfile.open(self.archive) as archive:
            self.assertEqual(archive.extractfile(self.args.name + '/DLSSNR').read(), b'new')
        self.assertEqual(self.checksum.read_text(),
                         self.builder.digest(self.archive) + '  ' + self.archive.name + '\n')
        self.assertEqual(set(self.output.iterdir()), {self.destination, self.archive, self.checksum})

    def test_build_and_archive_failure_preserve_previous_package(self):
        self.package(b'old')
        before = self.snapshot()
        for function in ['build', 'digest']:
            with self.subTest(function=function), mock.patch.object(
                    self.builder, 'build', side_effect=lambda args, repo, root: self.make_bundle(root, b'new')), mock.patch.object(
                    self.builder, function, side_effect=RuntimeError('injected failure')):
                with self.assertRaisesRegex(RuntimeError, 'injected failure'):
                    self.builder.package(self.args, REPO)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(len(list(self.output.iterdir())), 3)

    def test_each_publication_failure_restores_previous_package(self):
        self.package(b'old')
        before = self.snapshot()
        rename = Path.rename
        # Three backups followed by three replacements. Every individual move
        # may fail (e.g. disk or permissions error); the previous set must survive.
        for fail_at in range(1, 7):
            moves = 0

            def fail_one_move(source, target):
                nonlocal moves
                moves += 1
                if moves == fail_at:
                    raise OSError('injected publication failure')
                return rename(source, target)

            with self.subTest(fail_at=fail_at), mock.patch.object(Path, 'rename', fail_one_move):
                with self.assertRaisesRegex(OSError, 'injected publication failure'):
                    self.package()
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(len(list(self.output.iterdir())), 3)

    def test_interrupt_after_each_completed_move_restores_previous_package(self):
        self.package(b'old')
        before = self.snapshot()
        rename = Path.rename
        for interrupt_at in range(1, 7):
            moves = 0

            def interrupt_completed_move(source, target):
                nonlocal moves
                result = rename(source, target)
                moves += 1
                if moves == interrupt_at:
                    raise KeyboardInterrupt('interrupted after completed move')
                return result

            with self.subTest(interrupt_at=interrupt_at), mock.patch.object(
                    Path, 'rename', interrupt_completed_move):
                with self.assertRaises(KeyboardInterrupt):
                    self.package()
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(len(list(self.output.iterdir())), 3)

    def test_interrupt_during_rollback_preserves_every_previous_output(self):
        self.package(b'old')
        old_archive = self.archive.read_bytes()
        old_checksum = self.checksum.read_bytes()
        rename = Path.rename
        # Finish all six publication moves, interrupt, then interrupt again
        # after each completed rollback move. Recovery may be partial, but no
        # previous directory/archive/checksum may be discarded by cleanup.
        for interrupt_at in range(7, 13):
            moves = 0

            def interrupt_publish_and_rollback(source, target):
                nonlocal moves
                result = rename(source, target)
                moves += 1
                if moves in (6, interrupt_at):
                    raise KeyboardInterrupt('interrupted after completed move')
                return result

            with self.subTest(interrupt_at=interrupt_at), mock.patch.object(
                    Path, 'rename', interrupt_publish_and_rollback):
                with self.assertRaisesRegex(RuntimeError, 'recovery files kept'):
                    self.package()
            staging, = self.output.glob('.ubuntu-bundle-*')
            previous = staging / '.previous'
            for destination, expected in [(self.destination / 'DLSSNR', b'old'),
                                          (self.archive, old_archive),
                                          (self.checksum, old_checksum)]:
                backup = previous / destination.relative_to(self.output)
                self.assertTrue(any(path.is_file() and path.read_bytes() == expected
                                    for path in [destination, backup]))
            # Restore this fixture with real renames, ready for the next case.
            for destination in [self.destination, self.archive, self.checksum]:
                backup = previous / destination.name
                if backup.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    elif destination.exists():
                        destination.unlink()
                    backup.rename(destination)
            shutil.rmtree(staging)

    def test_unknown_existing_outputs_are_rejected_before_build(self):
        for shape in ['directory', 'wrong-target', 'incomplete', 'archive', 'checksum']:
            with self.subTest(shape=shape):
                if shape in ['directory', 'wrong-target', 'incomplete']:
                    self.destination.mkdir()
                    (self.destination / 'keep.txt').write_bytes(b'user file')
                    if shape != 'directory':
                        (self.destination / 'bundle-metadata.json').write_text(json.dumps({
                            'target': 'other' if shape == 'wrong-target' else 'Ubuntu 22.04 x86_64'}))
                else:
                    (self.archive if shape == 'archive' else self.checksum).write_bytes(b'user file')
                before = self.snapshot()
                with mock.patch.object(self.builder, 'build') as build:
                    with self.assertRaisesRegex(RuntimeError, 'unrecognized|Unrecognized'):
                        self.builder.package(self.args, REPO)
                    build.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                for item in self.output.iterdir():
                    shutil.rmtree(item) if item.is_dir() else item.unlink()

    def test_failed_rollback_keeps_previous_package_for_recovery(self):
        self.package(b'old')
        old_archive = self.archive.read_bytes()
        rename = Path.rename

        def fail_publish_and_restore(source, target):
            if source == self.archive or source.parent.name == '.previous':
                raise OSError('filesystem unavailable')
            return rename(source, target)

        with mock.patch.object(Path, 'rename', fail_publish_and_restore):
            with self.assertRaisesRegex(RuntimeError, 'recovery files kept'):
                self.package()
        staging, = self.output.glob('.ubuntu-bundle-*')
        self.assertEqual((staging / '.previous' / self.args.name / 'DLSSNR').read_bytes(), b'old')
        self.assertEqual(self.archive.read_bytes(), old_archive)

    def test_symlink_outputs_and_metadata_are_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        marker = outside / 'keep.txt'
        marker.write_bytes(b'untouched')
        self.package(b'old')
        for target in [self.destination, self.archive, self.checksum,
                       self.destination / 'bundle-metadata.json']:
            with self.subTest(target=target.name):
                backup = self.base / 'original'
                target.rename(backup)
                target.symlink_to(outside if backup.is_dir() else marker,
                                  target_is_directory=backup.is_dir())
                with mock.patch.object(self.builder, 'build') as build:
                    with self.assertRaisesRegex(RuntimeError, 'symlink|unrecognized|Unrecognized'):
                        self.builder.package(self.args, REPO)
                    build.assert_not_called()
                self.assertTrue(target.is_symlink())
                self.assertEqual(marker.read_bytes(), b'untouched')
                target.unlink()
                backup.rename(target)

    def test_unsafe_names_are_rejected_before_creating_files(self):
        for name in ['', '.', '..', '../outside', '/outside', 'folder/name',
                     'folder\\name', 'C:outside']:
            with self.subTest(name=name):
                self.args.name = name
                with mock.patch.object(self.builder, 'build') as build:
                    with self.assertRaisesRegex(RuntimeError, 'simple directory name'):
                        self.builder.package(self.args, REPO)
                    build.assert_not_called()
                self.assertEqual(list(self.output.iterdir()), [])


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
