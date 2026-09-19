#include "../core/ngx_snippet.h"
#include "../core/guard.h"
#include "../core/model_profile.h"
#include "../helper/vulkan_features.h"
#include <cstdio>
#include <cstring>

static void Trace(const char* message) {
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), message, (DWORD)std::strlen(message), &written, nullptr);
}

static bool CheckGeneration() {
    using Generation = dlssnr::GeForceGeneration;
    const struct { unsigned int vendor; const char* name; Generation expected; } cases[] = {
        {0x10de, "NVIDIA GeForce RTX 4090", Generation::Rtx40},
        {0x10de, "GeForce RTX 4070 Ti SUPER", Generation::Rtx40},
        {0x10de, "NVIDIA GeForce RTX 4050 Laptop GPU", Generation::Rtx40},
        {0x10de, "NVIDIA GeForce RTX 4090D", Generation::Rtx40},
        {0x10de, "NVIDIA GeForce RTX 5090", Generation::Rtx50},
        {0x10de, "NVIDIA GeForce RTX 5070 Ti Laptop GPU", Generation::Rtx50},
        {0x10de, "NVIDIA RTX 4000 Ada Generation", Generation::Other},
        {0x10de, "NVIDIA RTX PRO 5000 Blackwell", Generation::Other},
        {0x10de, "NVIDIA GeForce RTX 40900", Generation::Other},
        {0x10de, "NVIDIA GeForce RTX 4090 unknown", Generation::Other},
        {0x10de, "NVIDIA GeForce RTX 4", Generation::Other},
        {0x10de, "NVIDIA GeForce RTX 6090", Generation::Other},
        {0x10de, "NVIDIA GeForce RTX 3090", Generation::Other},
        {0x10de, "", Generation::Other},
        {0x1002, "NVIDIA GeForce RTX 4090", Generation::Other},
        {0, "NVIDIA GeForce RTX 5090", Generation::Other},
    };
    for (const auto& entry : cases) {
        if (dlssnr::ModelGeneration(entry.vendor, entry.name) != entry.expected) {
            std::fprintf(stderr, "Generation mismatch: vendor=%x name=%s\n", entry.vendor, entry.name);
            return false;
        }
    }
    return true;
}

static bool addressSupported = true;
static void VKAPI_CALL MockFeatures(VkPhysicalDevice, VkPhysicalDeviceFeatures2* output) {
    void* current = output->pNext;
    while (current) {
        VkStructureType type;
        void* next;
        std::memcpy(&type, current, sizeof(type));
        std::memcpy(&next, static_cast<char*>(current) + offsetof(VkBaseOutStructure, pNext), sizeof(next));
        if (type == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_BUFFER_DEVICE_ADDRESS_FEATURES) {
            auto* feature = reinterpret_cast<VkPhysicalDeviceBufferDeviceAddressFeatures*>(current);
            feature->bufferDeviceAddress = addressSupported;
            feature->bufferDeviceAddressCaptureReplay = VK_TRUE;
            feature->bufferDeviceAddressMultiDevice = VK_TRUE;
        } else if (type == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES) {
            reinterpret_cast<VkPhysicalDeviceSynchronization2Features*>(current)->synchronization2 = VK_TRUE;
        } else if (type == VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_OPTICAL_FLOW_FEATURES_NV) {
            reinterpret_cast<VkPhysicalDeviceOpticalFlowFeaturesNV*>(current)->opticalFlow = VK_TRUE;
        }
        current = next;
    }
}

static bool CheckDeviceFeatureContract() {
    for (bool sync : {false, true}) for (bool flow : {false, true}) {
        dlssnr::NeuralDeviceFeatures features;
        if (!features.Query(nullptr, MockFeatures, sync, flow) ||
            !features.address.bufferDeviceAddress || features.address.bufferDeviceAddressCaptureReplay ||
            features.address.bufferDeviceAddressMultiDevice ||
            bool(features.sync.synchronization2) != sync || bool(features.flow.opticalFlow) != flow) {
            std::fprintf(stderr, "Feature query failed sync=%d flow=%d returned=%u/%u/%u\n",
                sync, flow, features.address.bufferDeviceAddress, features.sync.synchronization2, features.flow.opticalFlow);
            return false;
        }
        // Follow the actual chain consumed by vkCreateDevice, not copies of flags.
        unsigned count = 0;
        void* current = &features.address;
        while (current && count < 4) {
            ++count;
            std::memcpy(&current, static_cast<char*>(current) + offsetof(VkBaseOutStructure, pNext), sizeof(current));
        }
        if (count != 1u + sync + flow || current) {
            std::fprintf(stderr, "Feature chain failed sync=%d flow=%d count=%u\n", sync, flow, count);
            return false;
        }
    }
    dlssnr::NeuralDeviceFeatures unsupported;
    addressSupported = false;
    const bool missingRejected = !unsupported.Query(nullptr, MockFeatures, true, true);
    addressSupported = true;
    return missingRejected && !unsupported.Query(nullptr, nullptr, false, false);
}

int main(int argc, char** argv) {
    if (argc != 4) {
        std::fprintf(stderr, "usage: ngx_runtime_test model-directory log-file mode\n");
        return 2;
    }
    Trace("[test] main entered\n");
    if (!CheckGeneration() || !CheckDeviceFeatureContract()) return 1;
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
    snippet.deviceProperties.vendorID = 0x10de;
    snippet.deviceProperties.deviceID = 0x2684;
    const char* name = "NVIDIA GeForce RTX 4090";
    if (std::strcmp(argv[3], "profile-rtx40-laptop") == 0) name = "NVIDIA GeForce RTX 4070 Laptop GPU";
    if (std::strcmp(argv[3], "profile-rtx50") == 0) name = "NVIDIA GeForce RTX 5090";
    if (std::strcmp(argv[3], "profile-workstation") == 0) name = "NVIDIA RTX 4000 Ada Generation";
    if (std::strcmp(argv[3], "profile-unknown") == 0) name = "NVIDIA GeForce RTX 6090";
    if (std::strcmp(argv[3], "profile-other-vendor") == 0) snippet.deviceProperties.vendorID = 0x1002;
    std::strncpy(snippet.deviceProperties.deviceName, name, sizeof(snippet.deviceProperties.deviceName) - 1);
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
    if (ok && (std::strcmp(argv[3], "resize") == 0 || std::strcmp(argv[3], "profile-rtx40-resize") == 0)) {
        const auto parameters = snippet.params;
        const auto module = snippet.snippet;
        const auto directory = snippet.binDir;
        // Even a later change in the selection inputs must not reload an NGX
        // context while its Vulkan device and feature lifetime remain active.
        std::strcpy(snippet.deviceProperties.deviceName, "NVIDIA GeForce RTX 5090");
        ok = dlssnr::NgxLoadAndInit(snippet, reinterpret_cast<VkInstance>(0x1110),
            reinterpret_cast<VkPhysicalDevice>(0x2220), reinterpret_cast<VkDevice>(0x3330),
            1280, 720, reinterpret_cast<VkCommandBuffer>(0x4440), {});
        passed = passed && snippet.params == parameters && snippet.featureW == 1280 && snippet.featureH == 720;
        passed = passed && snippet.snippet == module && snippet.binDir == directory;
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
