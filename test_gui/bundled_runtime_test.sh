#!/usr/bin/env bash
# CLI defaults can be tested without a GPU, Wine, or any real NVIDIA binaries.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export HOME="$work/home"
export XDG_CONFIG_HOME="$HOME/config" XDG_DATA_HOME="$HOME/data" XDG_STATE_HOME="$HOME/state"
export DLSSNR_INSTALL_DIR="$work/package" DLSSNR_BUNDLED_RUNNER="$work/package/wine"
export DLSSNR_UID="bundle-test-$$"
mkdir -p "$XDG_CONFIG_HOME/dlssnr" "$DLSSNR_INSTALL_DIR/helper/binaries"
trap 'rm -rf "$work" "/tmp/dlssnr-$DLSSNR_UID"' EXIT
printf '#!/bin/sh\nexit 0\n' > "$DLSSNR_BUNDLED_RUNNER"
chmod +x "$DLSSNR_BUNDLED_RUNNER"
touch "$DLSSNR_INSTALL_DIR/helper/binaries/nvngx_dlssnr.dll"
cat > "$XDG_CONFIG_HOME/dlssnr/config.ini" <<EOF
runner_type=proton
runner_path=$work/removed-runner
binaries=$work/missing-binaries
EOF
config="$(bash "$repo/dlssnr-helper" config)"
[[ "$config" == *"runner_type=wine"* ]]
[[ "$config" == *"runner_path=$DLSSNR_BUNDLED_RUNNER"* ]]
[[ "$config" == *"binaries=$DLSSNR_INSTALL_DIR/helper/binaries"* ]]
cp "$DLSSNR_BUNDLED_RUNNER" "$work/user-proton"
sed -i "s|runner_path=.*|runner_path=$work/user-proton|" "$XDG_CONFIG_HOME/dlssnr/config.ini"
config="$(bash "$repo/dlssnr-helper" config)"
[[ "$config" == *"runner_type=proton"* ]]
[[ "$config" == *"runner_path=$work/user-proton"* ]]
mkdir -p "$work/old package/helper/binaries" "$work/custom-models"
touch "$work/old package/helper/binaries/nvngx_dlssnr.dll" "$work/old package/bundle-metadata.json" \
      "$work/custom-models/nvngx_dlssnr.dll"
printf '\nbinaries=%s\n' "$work/old package/helper/binaries" > "$XDG_CONFIG_HOME/dlssnr/config.ini"
config="$(bash "$repo/dlssnr-helper" config)"
[[ "$config" == *"binaries=$DLSSNR_INSTALL_DIR/helper/binaries"* ]]
printf 'binaries=%s\n' "$work/custom-models" > "$XDG_CONFIG_HOME/dlssnr/config.ini"
config="$(bash "$repo/dlssnr-helper" config)"
[[ "$config" == *"binaries=$work/custom-models"* ]]
rm "$XDG_CONFIG_HOME/dlssnr/config.ini"
bash "$repo/dlssnr-helper" init >/dev/null
config="$(bash "$repo/dlssnr-helper" config)"
[[ "$config" == *"runner_type=wine"* ]]
[[ "$config" == *"runner_path=$DLSSNR_BUNDLED_RUNNER"* ]]
mkdir -p "$DLSSNR_INSTALL_DIR/runtime-dlls" "$DLSSNR_INSTALL_DIR/dxvk/2.7.1" \
         "$HOME/.local/share/dlssnr/prefix/wine/drive_c"
touch "$DLSSNR_INSTALL_DIR/helper/dlssnr_helper.exe" \
      "$DLSSNR_INSTALL_DIR/dxvk/2.7.1/vulkan-1.dll" \
      "$DLSSNR_INSTALL_DIR/runtime-dlls/dxgi.dll" \
      "$DLSSNR_INSTALL_DIR/runtime-dlls/nvapi64.dll"
diagnostics="$(bash "$repo/dlssnr-helper" doctor)"
[[ "$diagnostics" == *"$DLSSNR_INSTALL_DIR/runtime-dlls/dxgi.dll"* ]]
[[ "$diagnostics" == *"$DLSSNR_INSTALL_DIR/runtime-dlls/nvapi64.dll"* ]]
printf 'Bundled runtime defaults: passed\n'
