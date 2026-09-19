DLSSNR — Ubuntu 22.04 personal test package
==========================================

快速开始
--------
1. 将整个文件夹解压到 Ubuntu 22.04 的固定位置，双击 DLSSNR。
2. 已含模型的运行包直接点击 Start helper；未含模型时，首次在窗口中导入 nvngx_dlssnr.dll。
3. 游戏保持原来的 VKLayer_DLSS5=1 启动方式。在同一窗口调节效果、对比和截图。

双模型包会按实际使用的显卡自动选择：GeForce RTX 40 系使用 RTX40 候选，
RTX 50 系使用 SF-v2。无需手动切换。日志会记录选择结果和 DLL 版本。
更换包前先停止旧 helper。手动导入的模型目录仍优先；详细来源、哈希和
兼容性验证范围见 MODEL_PROFILES.md。自动选择不等于已验证实际画面效果。

后续更新使用固定的 dlssnr-ubuntu22.04-x86_64 文件夹和同名压缩包，
不再按版本号新增文件夹。构建成功后替换旧包，构建失败时保留旧包。

本版自动记录 NVAPI 与模型内部日志，无需另加启动参数。
主日志：~/.local/state/dlssnr/helper.log；模型原始日志：同目录下的 ngx/。
如果配置过 XDG_STATE_HOME，日志位于该目录下的 dlssnr/。
创建失败时，主日志中的 [ngx-log] 会摘取本次更新的模型日志末尾。
每次启动带时间和 helper 文件 SHA256，便于区分新旧测试。
“Feature=18 created=true”表示模型创建成功；进一步出现
“STATUS: neural frame completed count=1”才表示 helper 实际处理完成一帧。
实际显示还需游戏层接收并呈现该结果。

Qt、Wine、DXVK 和 NVAPI 已随包提供，无需自行安装。若包内已有模型 DLL，
界面会自动识别，无需导入。Check setup 用于检查，Details 显示准备进度和错误。
显卡驱动由系统提供：需要支持 Vulkan 1.4 的 NVIDIA 驱动，版本 575.51.02
或更新。当前完成了构建、界面及运行环境自检，尚未验证 RTX 40/50 的实际游戏效果。

不要只复制 DLSSNR 一个文件；它需要旁边的 runtime 等目录。
如果移动整个文件夹，重新打开 DLSSNR 即可更新本工具的注册路径。

1. Extract the complete folder to a permanent location in your home folder.
2. Double-click the DLSSNR executable to open the interface.
   start-dlssnr.sh is an equivalent terminal entry point.
3. Import your nvngx_dlssnr.dll in the GUI if it is not already included.
4. Start the helper in the GUI. Start your Vulkan game using its existing
   VKLayer_DLSS5=1 launch setting, then control and compare the effect in the GUI.

The package includes Qt, a private Wine 11 runner for the 64-bit helper, DXVK
and DXVK-NVAPI. You do not need to install a compiler, Qt SDK, system Wine,
Steam or Proton for the helper. No model DLL is downloaded automatically.

The host still supplies Ubuntu 22.04 Desktop x86_64, Python 3, Xorg or XWayland,
and a working NVIDIA Vulkan driver. DXVK 3.x requires Vulkan 1.4 support and
an NVIDIA driver at least 575.51.02. This is a runtime minimum, not a claim
that every RTX 40/50 GPU, game or model DLL is compatible. Real GPU testing
is still needed. The private Wine runner is not a general game launcher.

The GUI installs one user Vulkan manifest under
~/.local/share/vulkan/implicit_layer.d/dlssnr-portable-64.json
(and a separate 32-bit manifest only when a 32-bit layer is in the package).
It reuses an existing registration only if its library matches this package.
Conflicting installations are reported inside the GUI instead of loading an
old layer alongside a new helper.
No global environment settings or system files are changed. Games enable the
layer only through VKLayer_DLSS5=1. Run the launcher again after moving the
package so its user manifest points to the new location.

Your configuration, imported model DLLs, Wine prefix and logs remain in the
usual per-user DLSSNR folders. To remove the portable registration, delete only
the dlssnr-portable-64.json and dlssnr-portable-32.json files created by this
launcher, then remove the extracted package folder.

Build details and the exact component hashes are in bundle-metadata.json.
The package does not include glibc, NVIDIA or Mesa drivers. Other Linux
distributions and 32-bit Windows games are outside this package's scope.
