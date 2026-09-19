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

Model-selection cases exercise the Windows loader with an invalid DLL placed
in the directory that must not be selected. They cover GeForce RTX 40 desktop
and laptop profiles, RTX 50, a missing RTX 40 profile with a user-supplied flat
DLL, workstation/unknown names, another vendor, and model reuse during resize.
The classifier also checks incomplete and misleading model names. A test-only
version resource verifies both numeric and string DLL version diagnostics;
capability tests verify rejection-bit names and unknown bits without treating
a successful query as proof of support.

The mock DLLs and test executable are build outputs only. The runtime packager
copies named production files and must never include them. Per-case logs are
written to the Windows build directory.
