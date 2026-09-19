#!/usr/bin/env python3
"""Exercise NGX loading with mock DLLs on Windows or an isolated Wine prefix.

After tools/meson-build.sh, run on Windows with Python, or on Linux pass
--wine /path/to/bundle/bin/dlssnr-wine. No NVIDIA GPU or model DLL is used.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

CASES = ['runtime', 'bundled', 'query-error', 'create-error', 'create-exception',
         'evaluate-exception', 'hdr-fallback', 'resize', 'query-unsupported',
         'query-adapter-unsupported', 'profile-rtx40', 'profile-rtx40-laptop',
         'profile-rtx40-resize', 'profile-rtx50', 'profile-flat40',
         'profile-workstation', 'profile-other-vendor', 'profile-unknown', 'init-ext2', 'init-plain']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=Path('build/windows/windows'))
    parser.add_argument('--wine', type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--case', choices=CASES)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    executable = (args.executable or build / 'ngx_runtime_test.exe').resolve()
    required = [executable, build / 'ngx_mock_snippet.dll', build / 'ngx_mock_nvapi.dll']
    for path in required:
        if not path.is_file():
            parser.error('Missing test build: ' + str(path))
    if os.name != 'nt' and not args.wine:
        parser.error('Linux tests require --wine; a temporary prefix will be used')

    cases = [args.case] if args.case else list(CASES)
    if os.name == 'nt' and 'bundled' in cases:
        # Windows may already provide a real NVAPI in system32. The fallback case
        # requires an isolated Wine prefix where that runtime can be absent.
        cases.remove('bundled')
        print('bundled: skipped on native Windows (requires isolated Wine prefix)', flush=True)
    with tempfile.TemporaryDirectory(prefix='ngx-test-', dir=build) as directory:
        fixture = Path(directory)
        env = dict(os.environ)
        env.update(WINEDEBUG=os.environ.get('DLSSNR_TEST_WINEDEBUG', '-all'), WINEDLLOVERRIDES='nvapi64=n;mscoree,mshtml=',
                   WINEPREFIX=str(fixture / 'prefix'), WINEARCH='win64')
        wine = str(args.wine.resolve()) if args.wine else None

        def windows_path(path):
            return str(path) if os.name == 'nt' else 'Z:' + str(path)

        try:
            if wine:
                (fixture / 'prefix').mkdir()
                with (build / 'ngx-test-wineboot.log').open('wb') as boot_log:
                    subprocess.run([wine, 'wineboot', '--init'], env=env, check=True, timeout=60,
                                   stdout=boot_log, stderr=boot_log)
            for case in cases:
                env['DLSSNR_TEST_MODE'] = case
                work = fixture / case
                model = work / 'binaries'
                model.mkdir(parents=True)
                shutil.copy2(executable, work / 'ngx_runtime_test.exe')
                shutil.copy2(build / 'ngx_mock_snippet.dll', model / 'nvngx_dlssnr.dll')
                selected_model = model
                if case.startswith('profile-') and case != 'profile-flat40':
                    candidate = model / 'rtx40'
                    candidate.mkdir()
                    if case.startswith('profile-rtx40'):
                        selected_model = candidate
                        shutil.copy2(build / 'ngx_mock_snippet.dll', candidate / 'nvngx_dlssnr.dll')
                        # A wrong directory decision must fail actual LoadLibrary,
                        # independently of the selected-profile log message.
                        (model / 'nvngx_dlssnr.dll').write_text('wrong profile: not a DLL')
                    else:
                        (candidate / 'nvngx_dlssnr.dll').write_text('wrong profile: not a DLL')
                # Wine uses the same system32 location as the real portable launcher.
                # Native Windows uses the executable directory; never change system32.
                runtime = fixture / 'prefix/drive_c/windows/system32/nvapi64.dll' if wine else work / 'nvapi64.dll'
                if case == 'bundled':
                    runtime.unlink(missing_ok=True)
                    destination = model / 'nvapi64.dll'
                else:
                    destination = runtime
                shutil.copy2(build / 'ngx_mock_nvapi.dll', destination)
                log = work / 'helper.log'
                internal = work / 'ngx'
                internal.mkdir()
                stale = internal / 'nvngx_stale.log'
                stale.write_text('stale vendor failure must not be copied')
                os.utime(stale, (1, 1))
                (internal / 'unrelated.log').write_text('unrelated log must not be copied')
                env['__NGX_LOG_PATH_OVERRIDE'] = windows_path(internal)
                command = ([wine] if wine else []) + [str(work / 'ngx_runtime_test.exe'),
                    windows_path(model), windows_path(log), case]
                result = subprocess.run(command, cwd=work, env=env, timeout=30,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        errors='replace')
                output = log.read_text(errors='replace') if log.exists() else ''
                (build / ('ngx-test-' + case + '.log')).write_text(
                    result.stdout + result.stderr + output, errors='replace')
                if result.returncode:
                    raise AssertionError(case + ' exit=' + hex(result.returncode & 0xffffffff) + ': '
                                         + result.stdout + result.stderr + output)
                if 'DLSSNR.Available=0' in output or 'minGPU=' in output:
                    raise AssertionError('Misleading capability diagnostics: ' + output)
                assert output.count('[model] profile=') == 1, output
                assert '[model] version=310.8.42.0' in output, output
                assert '[model] fileVersion=310.8.mock.0' in output, output
                assert 'size=' in output and 'modifiedFileTime=' in output, output
                assert 'stale vendor failure' not in output and 'unrelated log' not in output, output
                if case == 'create-error':
                    assert '[ngx-log] mock vendor cause: cubin creation failed -3' in output, output
                    assert '[ngx-log] old diagnostic line 0\n' not in output, output
                    assert len(output) < 32000, len(output)
                if case == 'create-exception':
                    assert '[ngx-log] mock vendor diagnostic flushed at shutdown' in output, output
                if case == 'init-ext2':
                    assert 'VULKAN_Init_Ext2(ver=0x14) -> 0x1 (Success)' in output, output
                if case == 'init-plain':
                    assert 'VULKAN_Init(ver=0x14) -> 0x1 (Success)' in output, output
                loaded_path = windows_path(selected_model).replace('/', '\\').lower()
                assert ('path=' + loaded_path + '\\nvngx_dlssnr.dll') in output.replace('/', '\\').lower(), output
                if case.startswith('profile-rtx40'):
                    assert '[model] profile=rtx40 reason=selected-vulkan-geforce-rtx40' in output, output
                elif case == 'profile-rtx50':
                    assert '[model] profile=rtx50' in output, output
                elif case.startswith('profile-'):
                    assert '[model] profile=flat' in output, output
                if case == 'profile-flat40':
                    assert 'reason=rtx40-profile-missing-using-flat-file' in output, output
                if case == 'query-unsupported':
                    for reason in ['CheckNotPresent', 'DriverVersionUnsupported', 'AdapterUnsupported',
                                   'OSVersionBelowMinimumSupported', 'NotImplemented', 'UnknownBits',
                                   'unknownBits=0x80', 'AD100/Ada', 'reportedSupport=not-confirmed']:
                        assert reason in output, output
                if case == 'query-adapter-unsupported':
                    assert 'supportMask=0x4 (AdapterUnsupported)' in output, output
                    assert 'GB200/Blackwell' in output and 'reportedSupport=not-confirmed' in output, output
                if case in ('create-error', 'create-exception'):
                    assert 'created=true' not in output, output
                else:
                    assert 'created=true' in output, output
                print(result.stdout.strip(), flush=True)
        finally:
            if wine:
                # Bound process lifetime before TemporaryDirectory removes this prefix.
                server = args.wine.resolve().parent.parent / 'runtime/wine/bin/wineserver'
                if server.is_file():
                    subprocess.run([str(server), '-k'], env=env, timeout=10, check=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    subprocess.run([str(server), '-w'], env=env, timeout=10, check=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == '__main__':
    main()
