#include "../core/ngx_snippet.h"
#include "../core/guard.h"
#include <cstdio>
#include <cstring>

static void Trace(const char* message) {
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), message, (DWORD)std::strlen(message), &written, nullptr);
}

int main(int argc, char** argv) {
    if (argc != 4) {
        std::fprintf(stderr, "usage: ngx_runtime_test model-directory log-file mode\n");
        return 2;
    }
    Trace("[test] main entered\n");
    SetEnvironmentVariableA("DLSSNR_BIN_DIR", argv[1]);
    SetEnvironmentVariableA("DLSSNR_LOG", argv[2]);
    SetEnvironmentVariableA("DLSSNR_TEST_MODE", argv[3]);
    SetEnvironmentVariableA("DLSSNR_SKIP_NVAPI", nullptr);
    SetEnvironmentVariableA("DLSSNR_HDR", nullptr);
    Trace("[test] environment ready\n");
    dlssnr::g_layerModule = GetModuleHandleW(nullptr);
    dlssnr::InstallGuard();
    Trace("[test] guard installed\n");

    dlssnr::NgxSnippet snippet;
    const bool hdrFallback = std::strcmp(argv[3], "hdr-fallback") == 0;
    snippet.hdrActive = hdrFallback;
    Trace("[test] initializing NGX boundary\n");
    bool ok = dlssnr::NgxLoadAndInit(snippet, reinterpret_cast<VkInstance>(0x1110),
        reinterpret_cast<VkPhysicalDevice>(0x2220), reinterpret_cast<VkDevice>(0x3330),
        2560, 1440, reinterpret_cast<VkCommandBuffer>(0x4440), {});
    Trace("[test] initialization returned\n");

    bool passed = true;
    if (hdrFallback) {
        passed = !ok && !snippet.disabled;
        dlssnr::NgxSetHdr(snippet, false);
        ok = dlssnr::NgxLoadAndInit(snippet, reinterpret_cast<VkInstance>(0x1110),
            reinterpret_cast<VkPhysicalDevice>(0x2220), reinterpret_cast<VkDevice>(0x3330),
            2560, 1440, reinterpret_cast<VkCommandBuffer>(0x4440), {});
    }
    if (ok && std::strcmp(argv[3], "resize") == 0) {
        const auto parameters = snippet.params;
        ok = dlssnr::NgxLoadAndInit(snippet, reinterpret_cast<VkInstance>(0x1110),
            reinterpret_cast<VkPhysicalDevice>(0x2220), reinterpret_cast<VkDevice>(0x3330),
            1280, 720, reinterpret_cast<VkCommandBuffer>(0x4440), {});
        passed = passed && snippet.params == parameters && snippet.featureW == 1280 && snippet.featureH == 720;
    }
    const bool failCreate = std::strcmp(argv[3], "create-error") == 0 ||
                            std::strcmp(argv[3], "create-exception") == 0;
    if (failCreate) {
        passed = passed && !ok && snippet.disabled && !snippet.ready && !snippet.features[0];
    } else {
        passed = passed && ok && snippet.ready && !snippet.disabled && snippet.features[0];
        if (ok) {
            const bool evaluated = dlssnr::NgxEvaluatePass(snippet, 0,
                reinterpret_cast<VkCommandBuffer>(0x4440));
            const bool failEvaluate = std::strcmp(argv[3], "evaluate-exception") == 0;
            passed = passed && (failEvaluate ? (!evaluated && snippet.disabled) : evaluated);
        }
    }
    auto queries = snippet.snippet ? reinterpret_cast<unsigned int (*)()>(
        GetProcAddress(snippet.snippet, "DlssnrTestQueryCount")) : nullptr;
    passed = passed && queries && queries() == 1;
    auto initializations = snippet.snippet ? reinterpret_cast<unsigned int (*)()>(
        GetProcAddress(snippet.snippet, "DlssnrTestInitCount")) : nullptr;
    passed = passed && initializations && initializations() == 1;
    dlssnr::NgxTeardown(snippet, reinterpret_cast<VkDevice>(0x3330));
    passed = passed && !GetModuleHandleW(L"nvapi64.dll") && !GetModuleHandleW(L"nvngx_dlssnr.dll");
    std::printf("%s: %s (mock DLLs; no GPU processing)\n", argv[3], passed ? "PASS" : "FAIL");
    return passed ? 0 : 1;
}
