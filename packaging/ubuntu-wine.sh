#!/usr/bin/env bash
set -euo pipefail

# Only the helper inherits this library path. The GUI and game keep their own
# graphics libraries and never load these bundled Wine dependencies.
bundle_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
wine_root="$bundle_root/runtime/wine"
export WINESERVER="$wine_root/bin/wineserver"
export WINELOADER="$wine_root/bin/wine"
export WINEDLLPATH="$wine_root/lib/wine/x86_64-windows:$wine_root/lib/wine/x86_64-unix"
export LD_LIBRARY_PATH="$bundle_root/runtime/wine-libs:$wine_root/lib/wine/x86_64-unix"
export WINEARCH=win64
# Prefix setup should never prompt the user to install Mono or Gecko.
export WINEDLLOVERRIDES="mscoree,mshtml=${WINEDLLOVERRIDES:+;$WINEDLLOVERRIDES}"
exec "$WINELOADER" "$@"
