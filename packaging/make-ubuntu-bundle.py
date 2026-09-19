#!/usr/bin/env python3
"""Build a private Ubuntu 22.04 runtime without installing it on the host.

Run on Ubuntu 22.04 after tools/meson-build.sh. This script uses only Python's
standard library, dpkg-deb, ldd and qmake6; all downloads are pinned and checked.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


WINE_VERSION = '11.0.0.0~jammy-1'
WINE_BASE = 'https://dl.winehq.org/wine-builds/ubuntu/pool/main/w/wine/'
WINE_PACKAGES = {
    'wine-stable-amd64': '39d85b8f51728e44b5186a43126498149a885d49008ec31ac41f4548be8773bf',
    'wine-stable': '2866ffa79a28cbe64128f18a9172f8ba6dd7c2ff0c9491a92a8e6816faff8f1f',
}
# Use the system C runtime and graphics dispatch/driver stack. Mixing these
# with a user's NVIDIA installation would defeat portable packaging.
HOST_LIBRARIES = re.compile(
    r'^(?:ld-linux.*|lib(?:c|m|pthread|rt|dl|resolv|util|anl|nss_\w+)\.so(?:\..*)?'
    r'|lib(?:GL|EGL|GLX|OpenGL|GLdispatch|vulkan)\.so(?:\..*)?'
    r'|lib(?:nvidia|cuda|nvoptix|drm|gbm).*|.*_dri\.so)$')
# Wine loads these at runtime, so DT_NEEDED/ldd alone cannot discover them.
WINE_DYNAMIC_LIBRARIES = [
    'libfontconfig.so.1', 'libfreetype.so.6', 'libgnutls.so.30',
    'libXcursor.so.1', 'libXfixes.so.3', 'libXi.so.6', 'libXrandr.so.2',
    'libXrender.so.1', 'libXcomposite.so.1', 'libXinerama.so.1', 'libXxf86vm.so.1',
]


def run(*args, env=None):
    result = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(map(str, args)) + '\n'
                           + result.stdout + result.stderr)
    return result.stdout.strip()


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def download(url, expected, cache, supplied=None):
    target = supplied if supplied else cache / url.rsplit('/', 1)[-1]
    if not target.is_file():
        if supplied:
            raise RuntimeError('Required download does not exist: ' + str(target))
        print('Downloading ' + url, flush=True)
        temporary = target.with_suffix(target.suffix + '.partial')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'DLSSNR-bundle-builder'})
            with urllib.request.urlopen(request, timeout=60) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output)
            if digest(temporary) != expected:
                raise RuntimeError('SHA256 mismatch: ' + url)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    if digest(target) != expected:
        raise RuntimeError('SHA256 mismatch: ' + str(target))
    return target


def copy(source, target, executable=False):
    if not source.is_file():
        raise RuntimeError('Required build input is missing: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if executable:
        target.chmod(0o755)


def copy_script(source, target):
    # Git checkouts on Windows may have CRLF; a shipped shebang must not.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(), newline='\n')
    target.chmod(0o755)


def collect_libraries(inputs, destination, env=None, internal=None):
    destination.mkdir(parents=True, exist_ok=True)
    copied = {}
    for binary in inputs:
        output = run('ldd', str(binary), env=env)
        if '=> not found' in output:
            raise RuntimeError('Missing build-host runtime library for ' + str(binary) + '\n' + output)
        for line in output.splitlines():
            match = re.match(r'\s*(\S+)\s+=>\s+(/\S+)\s+\(', line)
            if not match:
                continue
            name, path = match.groups()
            source = Path(path).resolve()
            if HOST_LIBRARIES.match(name):
                continue
            if internal and (source == internal or internal in source.parents):
                continue
            if name in copied and copied[name] != str(source):
                raise RuntimeError('Conflicting library providers for ' + name)
            target = destination / name
            if target.exists() and digest(source) != digest(target):
                raise RuntimeError('Conflicting library contents for ' + name)
            if not target.exists():
                copy(source, target)
            copied[name] = str(source)
    return copied


def dynamic_library_paths():
    output = run('ldconfig', '-p')
    result = []
    for name in WINE_DYNAMIC_LIBRARIES:
        match = re.search(r'^\s*' + re.escape(name) + r' \([^\n]*x86-64[^\n]*\) => (.+)$',
                          output, re.MULTILINE)
        if not match:
            raise RuntimeError('Missing Wine runtime library on build host: ' + name)
        result.append((name, Path(match.group(1))))
    return result


def pinned_runtime_dlls(repo, root, cache):
    cli = (repo / 'dlssnr-helper').read_text()
    values = {}
    for key in ['DXVK_VERSION', 'DXVK_SHA256', 'DXVK_NVAPI_VERSION', 'DXVK_NVAPI_SHA256']:
        match = re.search(r'^' + key + r'="([^"]+)"$', cli, re.MULTILINE)
        if not match:
            raise RuntimeError('Missing runtime pin in dlssnr-helper: ' + key)
        values[key] = match.group(1)
    version = values['DXVK_VERSION']
    nvapi = values['DXVK_NVAPI_VERSION']
    packages = [
        ('https://github.com/doitsujin/dxvk/releases/download/v' + version + '/dxvk-' + version + '.tar.gz',
         values['DXVK_SHA256'], 'dxvk-' + version + '/x64/dxgi.dll', 'dxgi.dll'),
        ('https://github.com/jp7677/dxvk-nvapi/releases/download/v' + nvapi + '/dxvk-nvapi-v' + nvapi + '.tar.gz',
         values['DXVK_NVAPI_SHA256'], './x64/nvapi64.dll', 'nvapi64.dll'),
    ]
    for url, checksum, member, name in packages:
        archive = download(url, checksum, cache)
        with tarfile.open(archive) as stream:
            item = stream.getmember(member)
            if not item.isfile():
                raise RuntimeError('Runtime archive member is not a regular file: ' + member)
            content = stream.extractfile(item)
            target = root / 'runtime-dlls' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as output:
                shutil.copyfileobj(content, output)
            # Preserve upstream notices shipped alongside the selected DLL.
            for notice in stream.getmembers():
                if notice.isfile() and Path(notice.name).name.lower().startswith(('license', 'copying')):
                    destination = root / 'notices' / (name + '-' + Path(notice.name).name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(stream.extractfile(notice).read())
    return values


def build(args, repo, root):
    metadata = {'target': 'Ubuntu 22.04 x86_64', 'wine_version': WINE_VERSION,
                'wine_package_sha256': WINE_PACKAGES,
                'host_graphics': 'NVIDIA Vulkan 1.4 driver and host graphics dispatch libraries',
                'model_included': bool(args.binaries)}
    native = args.build_dir / 'native'
    for source, destination in [
        (native / 'gui/dlssnr_gui', root / 'bin/dlssnr_gui'),
        (native / 'layer_linux/libVkLayer_NV_dlssnr.so', root / 'layer/libVkLayer_NV_dlssnr.so'),
        (args.build_dir / 'windows/windows/dlssnr_helper.exe', root / 'helper/dlssnr_helper.exe'),
        (repo / 'layer_linux/manifest/VK_LAYER_NV_dlssnr.json', root / 'layer/manifest.json'),
        (repo / 'third_party/dxvk/2.7.1/x64/vulkan-1.dll', root / 'dxvk/2.7.1/vulkan-1.dll'),
        (repo / 'third_party/dxvk/2.7.1/LICENSE.txt', root / 'notices/dxvk-vulkan-bridge.txt'),
    ]:
        copy(source, destination, executable=destination.suffix in ('.so', '.exe') or destination.name == 'dlssnr_gui')
    optional32 = args.build_dir / 'linux32/layer_linux/libVkLayer_NV_dlssnr.so'
    if optional32.is_file():
        copy(optional32, root / 'layer32/libVkLayer_NV_dlssnr.so', executable=True)
    metadata['layer32_included'] = optional32.is_file()
    copy_script(repo / 'dlssnr-helper', root / 'dlssnr-helper')
    copy_script(repo / 'packaging/ubuntu-bundle-launch.sh', root / 'start-dlssnr.sh')
    copy_script(repo / 'packaging/ubuntu-wine.sh', root / 'bin/dlssnr-wine')
    run('cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        str(repo / 'packaging/ubuntu-bundle-main.c'), '-o', str(root / 'DLSSNR'))
    (root / 'DLSSNR').chmod(0o755)
    copy(repo / 'packaging/ubuntu-bundle-README.txt', root / 'README.txt')
    for document in ['LICENSE', 'ATTRIBUTION.md']:
        if (repo / document).is_file():
            copy(repo / document, root / 'notices' / document)

    qmake = shutil.which('qmake6')
    if not qmake:
        raise RuntimeError('Build prerequisite is missing: qmake6')
    plugins = Path(run(qmake, '-query', 'QT_INSTALL_PLUGINS'))
    plugin_inputs = []
    for name in ['libqxcb.so', 'libqoffscreen.so']:
        source = plugins / 'platforms' / name
        target = root / 'runtime/qt/plugins/platforms' / name
        copy(source, target)
        plugin_inputs.append(source)
    for source in sorted((plugins / 'imageformats').glob('*.so')):
        copy(source, root / 'runtime/qt/plugins/imageformats' / source.name)
        plugin_inputs.append(source)
    tools = [native / 'tools/runner_probe', native / 'tools/dlssnr-shmctl']
    for source in tools:
        # These tools are deliberately built as static ELF executables.
        copy(source, root / 'bin' / source.name, executable=True)
    metadata['qt_libraries'] = collect_libraries(
        [native / 'gui/dlssnr_gui'] + plugin_inputs, root / 'runtime/qt/lib')
    # The injected library uses the game's process and cannot use a private
    # loader. It must depend only on the Ubuntu baseline runtime.
    layer_deps = run('ldd', str(root / 'layer/libVkLayer_NV_dlssnr.so'))
    if '=> not found' in layer_deps:
        raise RuntimeError('Vulkan layer has unresolved dependencies:\n' + layer_deps)
    metadata['layer_dependencies'] = layer_deps

    print('Preparing private Wine 11 runtime', flush=True)
    with tempfile.TemporaryDirectory(prefix='wine-extract-', dir=args.cache_dir) as temporary:
        extraction = Path(temporary)
        for name, checksum in WINE_PACKAGES.items():
            url = WINE_BASE + name + '_' + WINE_VERSION + '_amd64.deb'
            supplied = args.wine_amd64_deb if name == 'wine-stable-amd64' else args.wine_common_deb
            archive = download(url, checksum, args.cache_dir, supplied)
            run('dpkg-deb', '-x', str(archive), str(extraction))
        wine = root / 'runtime/wine'
        shutil.copytree(extraction / 'opt/wine-stable', wine, symlinks=True)
        docs = extraction / 'usr/share/doc'
        if docs.is_dir():
            shutil.copytree(docs, root / 'notices/wine', symlinks=True)
    unix = wine / 'lib/wine/x86_64-unix'
    env = dict(os.environ, LD_LIBRARY_PATH=str(unix))
    wine_inputs = [wine / 'bin/wine', wine / 'bin/wineserver'] + sorted(unix.glob('*.so'))
    dynamic = dynamic_library_paths()
    metadata['wine_libraries'] = collect_libraries(
        wine_inputs + [path for _, path in dynamic], root / 'runtime/wine-libs', env, wine.resolve())
    for name, path in dynamic:
        copy(path, root / 'runtime/wine-libs' / name)
    version = run(str(root / 'bin/dlssnr-wine'), '--version')
    if version != 'wine-11.0':
        raise RuntimeError('Unexpected bundled Wine version: ' + version)
    metadata['wine_version_smoke'] = version
    metadata['runtime_dll_pins'] = pinned_runtime_dlls(repo, root, args.cache_dir)
    if args.binaries:
        if not (args.binaries / 'nvngx_dlssnr.dll').is_file():
            raise RuntimeError('--binaries must contain nvngx_dlssnr.dll')
        metadata['model_files'] = {}
        for source in args.binaries.iterdir():
            if source.is_file() and source.name.lower().endswith(('.dll', '.license.txt')):
                target = root / 'helper/binaries' / source.name
                copy(source, target)
                metadata['model_files'][source.name] = {
                    'size': target.stat().st_size, 'sha256': digest(target)}
    (root / 'bundle-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')


def main():
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=repo / 'build')
    parser.add_argument('--output-dir', type=Path, default=repo / 'dist')
    parser.add_argument('--cache-dir', type=Path, default=repo / 'build/ubuntu-bundle-cache')
    parser.add_argument('--name', default='dlssnr-ubuntu22.04-x86_64')
    parser.add_argument('--wine-amd64-deb', type=Path)
    parser.add_argument('--wine-common-deb', type=Path)
    parser.add_argument('--binaries', type=Path, help='Optional user-owned NVIDIA DLL directory')
    args = parser.parse_args()
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        parser.error('Build this package on Ubuntu 22.04 x86_64, including WSL Ubuntu 22.04.')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '22.04':
        parser.error('Use Ubuntu 22.04 to avoid silently shipping a newer glibc requirement.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', args.name):
        parser.error('--name must be a simple directory name')
    for tool in ['dpkg-deb', 'ldd', 'ldconfig', 'cc']:
        if not shutil.which(tool):
            parser.error('Build prerequisite is missing: ' + tool)
    args.build_dir = args.build_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.cache_dir = args.cache_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / args.name
    archive = args.output_dir / (args.name + '.tar.gz')
    if destination.exists() or archive.exists():
        parser.error('Output already exists; choose a new --name or --output-dir.')
    try:
        with tempfile.TemporaryDirectory(prefix='.ubuntu-bundle-', dir=args.output_dir) as temporary:
            root = Path(temporary) / args.name
            root.mkdir()
            build(args, repo, root)
            temporary_archive = Path(temporary) / (args.name + '.tar.gz')
            print('Creating runtime archive', flush=True)
            with tarfile.open(temporary_archive, 'w:gz', compresslevel=6) as output:
                output.add(root, arcname=args.name)
            root.rename(destination)
            temporary_archive.rename(archive)
        print('Built ' + str(archive), flush=True)
        print('Extracted directory: ' + str(destination), flush=True)
        checksum = digest(archive)
        archive.with_suffix(archive.suffix + '.sha256').write_text(
            checksum + '  ' + archive.name + '\n')
        print('SHA256: ' + checksum, flush=True)
    except (OSError, RuntimeError, tarfile.TarError, KeyError) as error:
        print('Bundle build failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
