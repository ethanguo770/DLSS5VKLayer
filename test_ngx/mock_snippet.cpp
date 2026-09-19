#include "../core/ngx_abi.h"
#include <cstddef>
#include <cstdlib>
#include <cstring>

// Define the public discovery ABI independently from the production declarations.
// Reference: NVIDIA/DLSS include/nvsdk_ngx_defs.h and include/nvsdk_ngx_vk.h.
namespace reference {
struct Project { const char* id; int engine; const char* version; };
struct Identifier { int type; union { Project project; unsigned long long app; } value; };
struct Discovery { unsigned int version; int feature; Identifier id;
                   const wchar_t* path; const void* info; };
struct Requirement { unsigned int supported; unsigned int architecture; char os[255]; };
static_assert(sizeof(Discovery) == 56 && offsetof(Discovery, path) == 40);
static_assert(sizeof(Requirement) == 264 && offsetof(Requirement, os) == 8);
}

static unsigned int queries = 0;
static unsigned int initializations = 0;
static unsigned int creations = 0;
static bool validQuery = false;
static int featureHandle = 18;

static bool Mode(const char* value) {
    const char* mode = std::getenv("DLSSNR_TEST_MODE");
    return mode && std::strcmp(mode, value) == 0;
}

#define EXPORT extern "C" __declspec(dllexport)

EXPORT unsigned int DlssnrTestQueryCount() { return queries; }
EXPORT unsigned int DlssnrTestInitCount() { return initializations; }

EXPORT NVSDK_NGX_Result NVSDK_NGX_VULKAN_Init_Ext(
    unsigned long long, const wchar_t*, VkInstance, VkPhysicalDevice, VkDevice,
    NVSDK_NGX_Version, const void*) {
    ++initializations;
    // Keep the same import that the real snippet's caller hook requires.
    wchar_t caller[MAX_PATH]{};
    if (!GetModuleFileNameW(GetModuleHandleW(nullptr), caller, MAX_PATH))
        return NVSDK_NGX_Result_FAIL_PlatformError;
    return NVSDK_NGX_Result_Success;
}

EXPORT NVSDK_NGX_Result NVSDK_NGX_VULKAN_GetFeatureRequirements(
    VkInstance instance, VkPhysicalDevice device, const reference::Discovery* discovery,
    reference::Requirement* output) {
    ++queries;
    // The old three-argument call points discovery at an unrelated zero-filled
    // structure. Reject it before touching its uninitialised fourth argument.
    if (instance != reinterpret_cast<VkInstance>(0x1110) ||
        device != reinterpret_cast<VkPhysicalDevice>(0x2220) || !discovery ||
        discovery->version < 0x13 || discovery->feature != 18 || !output)
        return NVSDK_NGX_Result_FAIL_InvalidParameter;
    if (discovery->id.type != 0 || discovery->id.value.app != 0x0876232cULL ||
        !discovery->path || !*discovery->path)
        return NVSDK_NGX_Result_FAIL_InvalidParameter;
    validQuery = true;
    if (Mode("query-error")) return NVSDK_NGX_Result_FAIL_InvalidParameter;
    output->supported = Mode("query-unsupported") ? 2 : 0;
    output->architecture = 0x1234;
    std::memset(output->os, 'X', sizeof(output->os)); // also tests bounded logging
    return NVSDK_NGX_Result_Success;
}

EXPORT NVSDK_NGX_Result NVSDK_NGX_VULKAN_CreateFeature(
    VkCommandBuffer, int feature, NVSDK_NGX_Parameter* params, NVSDK_NGX_Handle** handle) {
    *handle = nullptr;
    const HMODULE nvapi = GetModuleHandleW(L"nvapi64.dll");
    auto marker = nvapi ? reinterpret_cast<unsigned int (*)()>(
        GetProcAddress(nvapi, "DlssnrTestNvapiMarker")) : nullptr;
    if (!marker || marker() != 0x4e565041) return NVSDK_NGX_Result_FAIL_PlatformError;
    if (!validQuery || feature != 18) return NVSDK_NGX_Result_FAIL_InvalidParameter;
    HMODULE self = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<const wchar_t*>(&DlssnrTestQueryCount), &self);
    wchar_t path[MAX_PATH]{};
    if (!GetModuleFileNameW(self, path, MAX_PATH)) return NVSDK_NGX_Result_FAIL_PlatformError;
    ++creations;
    unsigned int width = 0, height = 0;
    params->Get("Width", &width);
    params->Get("Height", &height);
    if (Mode("resize") && creations == 2 && (width != 1280 || height != 720))
        return NVSDK_NGX_Result_FAIL_InvalidParameter;
    if (Mode("create-error")) return NVSDK_NGX_Result_FAIL_PlatformError;
    if (Mode("create-exception")) {
        RaiseException(EXCEPTION_ACCESS_VIOLATION, 0, 0, nullptr);
        return NVSDK_NGX_Result_FAIL_SEH;
    }
    unsigned int flags = 0;
    params->Get("Feature_Flags", &flags);
    if (Mode("hdr-fallback") && (flags & 1)) return NVSDK_NGX_Result_FAIL_PlatformError;
    *handle = reinterpret_cast<NVSDK_NGX_Handle*>(&featureHandle);
    return NVSDK_NGX_Result_Success;
}

EXPORT NVSDK_NGX_Result NVSDK_NGX_VULKAN_EvaluateFeature(
    VkCommandBuffer, const NVSDK_NGX_Handle*, const NVSDK_NGX_Parameter*, void*) {
    if (Mode("evaluate-exception")) {
        RaiseException(EXCEPTION_ACCESS_VIOLATION, 0, 0, nullptr);
        return NVSDK_NGX_Result_FAIL_SEH;
    }
    return NVSDK_NGX_Result_Success;
}
EXPORT NVSDK_NGX_Result NVSDK_NGX_VULKAN_ReleaseFeature(NVSDK_NGX_Handle*) {
    return NVSDK_NGX_Result_Success;
}
EXPORT NVSDK_NGX_Result NVSDK_NGX_VULKAN_Shutdown1(VkDevice) {
    return NVSDK_NGX_Result_Success;
}
