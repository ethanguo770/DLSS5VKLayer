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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=Path('build/windows/windows'))
    parser.add_argument('--wine', type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--case', choices=['runtime', 'bundled', 'query-error', 'create-error',
                                          'create-exception', 'evaluate-exception', 'hdr-fallback',
                                          'resize', 'query-unsupported'])
    args = parser.parse_args()
    build = args.build_dir.resolve()
    executable = (args.executable or build / 'ngx_runtime_test.exe').resolve()
    required = [executable, build / 'ngx_mock_snippet.dll', build / 'ngx_mock_nvapi.dll']
    for path in required:
        if not path.is_file():
            parser.error('Missing test build: ' + str(path))
    if os.name != 'nt' and not args.wine:
        parser.error('Linux tests require --wine; a temporary prefix will be used')

    cases = [args.case] if args.case else ['runtime', 'bundled', 'query-error', 'create-error',
                                         'create-exception', 'evaluate-exception', 'hdr-fallback',
                                         'resize', 'query-unsupported']
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
