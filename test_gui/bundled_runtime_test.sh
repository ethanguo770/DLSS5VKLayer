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

# Exercise the actual launch boundary without Wine or a GPU. The runner leaves
# its environment in the existing helper log, then stays visible to status.
cat > "$DLSSNR_BUNDLED_RUNNER" <<'EOF'
#!/usr/bin/env bash
printf '[fixture] nvapi=<%s> wine=<%s> arch=<%s> extraLog=<%s>\n' \
  "$DXVK_NVAPI_LOG_LEVEL" "$WINEDEBUG" "${DXVK_NVAPI_GPU_ARCH-}" "${DXVK_NVAPI_LOG_PATH-}"
printf '[fixture] ngxEnable=<%s> ngxLevel=<%s> ngxPath=<%s>\n' \
  "$__NGX_ENABLE_OVERRIDE_LOG_PATH" "$__NGX_LOG_LEVEL" "$__NGX_LOG_PATH_OVERRIDE"
exec -a dlssnr_helper.exe sleep 60
EOF
stop_fixture() {
  local pidfile="/tmp/dlssnr-$DLSSNR_UID/helper.pid" pid
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    kill -TERM -- "-$pid" 2>/dev/null || true
    rm -f "$pidfile"
  fi
}
trap 'stop_fixture; rm -rf "$work" "/tmp/dlssnr-$DLSSNR_UID"' EXIT
helper_log="$XDG_STATE_HOME/dlssnr/helper.log"
unset DXVK_NVAPI_LOG_LEVEL DXVK_NVAPI_LOG_PATH WINEDEBUG DXVK_NVAPI_GPU_ARCH
unset __NGX_ENABLE_OVERRIDE_LOG_PATH __NGX_LOG_PATH_OVERRIDE __NGX_LOG_LEVEL
start_output="$(bash "$repo/dlssnr-helper" start)"
[[ "$start_output" == *'helper started'* ]]
grep -Fq '[fixture] nvapi=<info> wine=<-all> arch=<> extraLog=<>' "$helper_log"
grep -Fq '[dlssnr-launch] === session ' "$helper_log"
grep -Fq '[dlssnr-launch] helper sha256=' "$helper_log"
grep -Fq "[fixture] ngxEnable=<1> ngxLevel=<2> ngxPath=<Z:$XDG_STATE_HOME/dlssnr/ngx>" "$helper_log"
[[ -d "$XDG_STATE_HOME/dlssnr/ngx" ]]
stop_fixture

# Explicit none/empty settings remain user-owned. The second start reuses the
# same log and records both the changed diagnostic level and GPU override.
export DXVK_NVAPI_LOG_LEVEL=none WINEDEBUG='' DXVK_NVAPI_GPU_ARCH=AD100
export __NGX_ENABLE_OVERRIDE_LOG_PATH=0 __NGX_LOG_LEVEL=0 __NGX_LOG_PATH_OVERRIDE='C:/my diagnostics'
start_output="$(bash "$repo/dlssnr-helper" start)"
[[ "$start_output" == *'helper started'* ]]
grep -Fq '[fixture] nvapi=<none> wine=<> arch=<AD100> extraLog=<>' "$helper_log"
grep -Fq '[dlssnr-launch] DXVK_NVAPI_GPU_ARCH=AD100' "$helper_log"
grep -Fq '[fixture] ngxEnable=<0> ngxLevel=<0> ngxPath=<C:/my diagnostics>' "$helper_log"
[[ "$(grep -Fc '[dlssnr-launch] === session ' "$helper_log")" == 2 ]]
[[ ! -e "$XDG_STATE_HOME/dlssnr/nvapi64.log" ]]
stop_fixture
printf 'Bundled runtime defaults: passed\n'
