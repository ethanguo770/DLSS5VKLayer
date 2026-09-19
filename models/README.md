# DLL 下载

两份 DLL 一起放在 GitHub Release 中，可直接下载到其他电脑：

- [下载 DLL 压缩包](https://github.com/ethanguo770/DLSS5VKLayer/releases/download/model-dlls-310.8/dlssnr-models-310.8.zip)
- [下载 SHA256 校验文件](https://github.com/ethanguo770/DLSS5VKLayer/releases/download/model-dlls-310.8/dlssnr-models-310.8.zip.sha256)
- [查看发布页面](https://github.com/ethanguo770/DLSS5VKLayer/releases/tag/model-dlls-310.8)

停止辅助程序后，将压缩包内的内容解压到运行包的 `helper/binaries/`。保留 `rtx40` 子目录，解压后应为：

```text
helper/binaries/nvngx_dlssnr.dll
helper/binaries/rtx40/nvngx_dlssnr.dll
```

基础 DLL 用于 RTX 50，`rtx40` 中是 RTX 40 候选 DLL；启动器会根据实际选中的显卡自动选择。

从源码构建时，将同一压缩包的内容解压到仓库的 `models/` 目录，并给打包命令传入 `--binaries models`。

版本、大小和 SHA256 见[模型说明](../packaging/model-profiles.md)。这些是当前测试使用的 DLL，提供下载不代表已解决 RTX 4090 上的 Linux/Vulkan 模型创建失败问题。
