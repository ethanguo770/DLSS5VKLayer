#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

MESON=${MESON:-meson}
NINJA=${NINJA:-ninja}
BUILD_ROOT=${DLSSNR_BUILD_ROOT:-build}

# Jammy's Qt 6 tools live in libexec, and its Meson predates the qmake6
# executable name. These are build-time paths only; deployed users need no SDK.
if command -v qmake6 >/dev/null 2>&1; then
    export QMAKE="${QMAKE:-$(command -v qmake6)}"
    qt_libexec="$("$QMAKE" -query QT_HOST_LIBEXECS 2>/dev/null || true)"
    if [ -d "$qt_libexec" ]; then
        export PATH="$qt_libexec:$PATH"
    fi
fi

windows_cross=(--cross-file meson/cross-clang-mingw64.ini)
if [ -d /usr/lib/gcc/x86_64-w64-mingw32/10-posix/include/c++ ]; then
    windows_cross+=(--cross-file meson/cross-clang-mingw64-ubuntu22.ini)
fi

setup_build() {
    local dir="$1"
    shift
    local config_stamp="$dir/.dlssnr-meson-config"
    local requested_config
    requested_config="$(printf '%s\n' "$@"; sha256sum meson/*.ini)"

    if [ -f "$dir/meson-private/coredata.dat" ] &&
       [ -f "$config_stamp" ] &&
       [ "$(cat "$config_stamp")" = "$requested_config" ]; then
        "$MESON" setup --reconfigure "$dir" "$@"
    elif [ -f "$dir/meson-private/coredata.dat" ]; then
        "$MESON" setup --wipe "$dir" "$@"
    else
        "$MESON" setup "$dir" "$@"
    fi
    printf '%s' "$requested_config" > "$config_stamp"
}

build_all() {
    setup_build "$BUILD_ROOT/native" --native-file meson/native-clang.ini
    setup_build "$BUILD_ROOT/linux32" \
    --native-file meson/native-clang.ini \
    --cross-file meson/cross-clang-linux32.ini
    setup_build "$BUILD_ROOT/windows" \
    --native-file meson/native-clang.ini \
    "${windows_cross[@]}"

    "$MESON" compile -C "$BUILD_ROOT/native"
    "$MESON" compile -C "$BUILD_ROOT/linux32"
    "$MESON" compile -C "$BUILD_ROOT/windows"
}

analyze_all() {
    command -v scan-build >/dev/null 2>&1 || {
        echo "error: scan-build not found (install clang-tools)" >&2
        exit 1
    }

    setup_build "$BUILD_ROOT/native" --native-file meson/native-clang.ini
    setup_build "$BUILD_ROOT/linux32" \
        --native-file meson/native-clang.ini \
        --cross-file meson/cross-clang-linux32.ini
    setup_build "$BUILD_ROOT/windows" \
        --native-file meson/native-clang.ini \
        "${windows_cross[@]}"

    "$NINJA" -C "$BUILD_ROOT/native" clean
    "$MESON" compile -C "$BUILD_ROOT/native" analyze

    "$NINJA" -C "$BUILD_ROOT/linux32" clean
    "$MESON" compile -C "$BUILD_ROOT/linux32" analyze

    "$NINJA" -C "$BUILD_ROOT/windows" clean
    "$MESON" compile -C "$BUILD_ROOT/windows" analyze-windows
}

case "${1:-build}" in
    build)
        build_all
        ;;
    analyze)
        analyze_all
        ;;
    test)
        exec "$MESON" test -C "$BUILD_ROOT/native" --print-errorlogs
        ;;
    *)
        echo "usage: $0 [build|test|analyze]" >&2
        exit 2
        ;;
esac

echo "built:"
echo "  $BUILD_ROOT/native/layer_linux/libVkLayer_NV_dlssnr.so"
echo "  $BUILD_ROOT/linux32/layer_linux/libVkLayer_NV_dlssnr.so"
echo "  $BUILD_ROOT/windows/windows/dlssnr_helper.exe"
echo "  $BUILD_ROOT/windows/windows/smoke.exe"
echo "  $BUILD_ROOT/native/tools/runner_probe"
echo "  $BUILD_ROOT/native/tools/dlssnr-shmctl"
echo "  $BUILD_ROOT/native/gui/dlssnr_gui"
echo "  $BUILD_ROOT/native/test_gui/binder_test"
