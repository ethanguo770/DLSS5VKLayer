# NGX runtime regression tests

Build with `bash tools/meson-build.sh`, then run from the repository root:

```bash
python3 test_ngx/run_runtime_tests.py --wine /absolute/path/to/bundle/bin/dlssnr-wine
```

On Windows, omit `--wine`. The bundled-file fallback case is skipped there
because the installed NVIDIA driver may already supply NVAPI. Wine tests use
a temporary prefix and place the mock NVAPI in its `system32` directory, just
as the portable launcher installs the real runtime.

The independent mock DLL checks the four-argument discovery ABI, runtime DLL
loading, failed queries, create/evaluate exceptions, HDR fallback, window-size
rebuilds, and module ownership on teardown. It makes no GPU calls and cannot
establish whether the real model works on a particular driver or GPU.

The mock DLLs and test executable are build outputs only. The runtime packager
copies named production files and must never include them. Per-case logs are
written to the Windows build directory.
