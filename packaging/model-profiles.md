# Automatic RTX 40/50 model selection

The helper chooses a model using the NVIDIA Vulkan device it actually selected.
GeForce RTX 40-series GPUs use `helper/binaries/rtx40/nvngx_dlssnr.dll` when it
exists. GeForce RTX 50-series GPUs use `helper/binaries/nvngx_dlssnr.dll`.
Other devices and user-imported flat model folders use the base DLL. A missing
RTX 40 profile also uses the base DLL and is reported in the helper log.
Workstation names such as RTX 4000 are not treated as GeForce RTX 40-series.

Selection happens on first model initialization. Window resizing and HDR
changes reuse the selected runtime. Selection does not guarantee that the
model can create a feature or process frames on the current driver.

The personal dual-model package prepared on 2026-09-20 uses these exact files:

| Role | Embedded version | Size | SHA256 |
| --- | --- | --- | --- |
| Base / RTX 50 | 310.8.SF.0 (SF-v2 distribution) | 165830144 | `6eb209e764f39872625debd6abaf45e2bb6322f6f270f781f70c059ae30b3927` |
| RTX 40 candidate | 310.8.0.0 (RTX40 distribution) | 165840496 | `4b8d19bc3eff58a084f5eca7489c921501c203450169fb82ff4f649a4482ba05` |

These are community-modified NVIDIA NR libraries, not two official NVIDIA
compatibility releases. The SF-v2 file has no Authenticode signature. The
RTX40 file retains a signature whose digest no longer matches after community
modification; its SHA256 does match the published community file identity.
The version number alone does not distinguish every community revision.
The package's `bundle-metadata.json` records the hashes actually included;
model-free and custom builds may contain different files.

Sources checked on 2026-09-20:

- [SF-v2 author verification](https://github.com/2600th/dlss5-video-player/blob/main/docs/VERIFICATION-2026-09-09-RTX5090.md)
  identifies the base file by its hash and reports Windows RTX 4080 SUPER and
  RTX 5090 testing. This does not establish this helper's Linux/Vulkan support.
- [RTX40 release](https://github.com/RankFTW/rhi-repo/releases/tag/dlssnr-310.8.0-RTX40)
  supplies `nvngx_dlssnr_310.8.0-RTX40.zip`, SHA256
  `46124cfaef532ad5f6da07494772ea8c1b3e719f934e254385697f38d1289e3f`.
- [Published file manifest](https://github.com/dubrovskiy-yevhen-stakelogic/vice-city-vr/blob/main/tools/dlss/packages.json)
  records the RTX40 DLL's exact hash and size. Both the ZIP and extracted DLL
  were checked against these values before packaging.

No successful Ubuntu 22.04 + RTX 4090 + direct NGX Vulkan test was verified for
either exact file during this work. The helper log reports the selected GPU,
profile, model identity, support result, and actual creation/evaluation failures.
`GetFeatureRequirements` succeeding only means the query ran; a nonzero support
mask still reports an unsupported condition. Even successful feature creation
alone is not proof that game frames were evaluated and displayed.

Stop the helper before switching packages or importing a model. Opening a new
portable GUI migrates a path into an older portable package to the current
model set. User-imported/custom model folders retain their precedence.
