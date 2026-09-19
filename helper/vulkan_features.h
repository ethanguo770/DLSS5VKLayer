#pragma once
#include <vulkan/vulkan.h>

namespace dlssnr {

// Extension names alone do not enable their associated device features.
// Keep this chain alive until vkCreateDevice returns. Query into separate
// structures so capture/replay and multi-device addressing remain disabled.
struct NeuralDeviceFeatures {
    VkPhysicalDeviceBufferDeviceAddressFeatures address{};
    VkPhysicalDeviceSynchronization2Features sync{};
    VkPhysicalDeviceOpticalFlowFeaturesNV flow{};

    bool Query(VkPhysicalDevice physical, PFN_vkGetPhysicalDeviceFeatures2 query,
               bool wantSync, bool wantFlow) {
        *this = {};
        address.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_BUFFER_DEVICE_ADDRESS_FEATURES;
        sync.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES;
        flow.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_OPTICAL_FLOW_FEATURES_NV;
        if (!query) return false;
        NeuralDeviceFeatures supported;
        supported.address.sType = address.sType;
        supported.sync.sType = sync.sType;
        supported.flow.sType = flow.sType;
        supported.address.pNext = wantSync ? static_cast<void*>(&supported.sync) :
                                  wantFlow ? static_cast<void*>(&supported.flow) : nullptr;
        supported.sync.pNext = wantFlow ? &supported.flow : nullptr;
        VkPhysicalDeviceFeatures2 features{};
        features.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
        features.pNext = &supported.address;
        query(physical, &features);
        address.bufferDeviceAddress = supported.address.bufferDeviceAddress;
        sync.synchronization2 = wantSync && supported.sync.synchronization2;
        flow.opticalFlow = wantFlow && supported.flow.opticalFlow;
        address.pNext = sync.synchronization2 ? static_cast<void*>(&sync) :
                        flow.opticalFlow ? static_cast<void*>(&flow) : nullptr;
        sync.pNext = flow.opticalFlow ? &flow : nullptr;
        return address.bufferDeviceAddress == VK_TRUE;
    }
};

} // namespace dlssnr
