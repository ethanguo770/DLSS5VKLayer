#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [ "$(uname -m)" != x86_64 ]; then
    echo 'This package requires Ubuntu 22.04 x86_64.' >&2
    exit 1
fi
# Vulkan needs a persistent manifest so a game launched outside this GUI can
# find the layer. Register only our own file; do not change login variables.
unset DLSSNR_SETUP_ERROR
if setup_output="$(python3 - "$bundle_root" 2>&1 <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(sys.argv[1])
data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
config_home = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
destination = data_home / 'vulkan/implicit_layer.d'
search = [destination, config_home / 'vulkan/implicit_layer.d']
search += [Path(p) / 'vulkan/implicit_layer.d' for p in
           os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
search += [Path(p) / 'vulkan/implicit_layer.d' for p in
           os.environ.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':') if p]
search += [Path('/etc/vulkan/implicit_layer.d')]

def digest(file):
    value = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.digest()

for bits, directory, name in [('64', 'layer', 'VK_LAYER_NV_dlssnr'),
                              ('32', 'layer32', 'VK_LAYER_NV_dlssnr_32')]:
    library = root / directory / 'libVkLayer_NV_dlssnr.so'
    if not library.is_file():
        if bits == '64':
            raise SystemExit('Package is incomplete: missing the 64-bit Vulkan layer.')
        continue
    target = destination / ('dlssnr-portable-' + bits + '.json')
    if target.is_symlink():
        raise SystemExit('Refusing to replace a symlinked manifest: ' + str(target))
    existing = []
    for folder in dict.fromkeys(search):
        for file in folder.glob('*.json'):
            if file == target:
                continue
            try:
                document = json.loads(file.read_text())
                layers = document.get('layers', [document.get('layer', {})])
                for layer in layers:
                    if layer.get('name') == name:
                        registered = Path(layer.get('library_path', ''))
                        if not registered.is_absolute():
                            registered = file.parent / registered
                        existing.append((file, registered))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    if existing:
        # A previously created portable manifest would otherwise become a
        # duplicate if the user subsequently installed a system package.
        if target.exists():
            raise SystemExit('Duplicate Vulkan layer installations found. Keep one installation: '
                             + str(target) + ' and ' + ', '.join(map(str, existing)))
        for file, registered in existing:
            try:
                compatible = registered.is_file() and digest(registered) == digest(library)
            except OSError:
                compatible = False
            if not compatible:
                raise SystemExit('An existing DLSSNR layer differs from this package: ' + str(file)
                                 + '. Remove that installation before using this portable package.')
        print('Using the matching Vulkan layer registration: '
              + ', '.join(str(file) for file, _ in existing))
        continue
    document = json.loads((root / 'layer/manifest.json').read_text())
    document['layer'].update(name=name, library_path=str(library), library_arch=bits)
    destination.mkdir(parents=True, exist_ok=True)
    # Never overwrite an unrelated file even when it happens to use our name.
    if target.exists():
        try:
            previous = json.loads(target.read_text())
        except (OSError, ValueError) as error:
            raise SystemExit('Cannot update existing layer manifest: ' + str(target)) from error
        if previous.get('dlssnr_portable_manifest') != 1:
            raise SystemExit('Refusing to replace an unrelated manifest: ' + str(target))
    document['dlssnr_portable_manifest'] = 1
    fd, temporary = tempfile.mkstemp(prefix='.dlssnr-', suffix='.tmp', dir=destination)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(document, stream, indent=2)
            stream.write('\n')
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
PY
)"; then
    [ -z "$setup_output" ] || printf '%s\n' "$setup_output"
else
    export DLSSNR_SETUP_ERROR="$setup_output"
    printf '%s\n' "$DLSSNR_SETUP_ERROR" >&2
fi

if [ "${1:-}" = --register-layer-only ]; then
    [ -z "${DLSSNR_SETUP_ERROR:-}" ] || exit 1
    exit 0
fi
export DLSSNR_INSTALL_DIR="$bundle_root"
export DLSSNR_HELPER_CLI="$bundle_root/dlssnr-helper"
export DLSSNR_BUNDLED_RUNNER="$bundle_root/bin/dlssnr-wine"
export QT_PLUGIN_PATH="$bundle_root/runtime/qt/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PLUGIN_PATH/platforms"
# XWayland is present in Ubuntu Desktop's Wayland session. The same XCB plugin
# works there and in an Xorg session without bundling another display stack.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
exec env -u LD_LIBRARY_PATH /lib64/ld-linux-x86-64.so.2 \
    --library-path "$bundle_root/runtime/qt/lib" "$bundle_root/bin/dlssnr_gui" "$@"
