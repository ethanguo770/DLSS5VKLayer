#pragma once
#include <cstdint>
#include <initializer_list>
#include <string_view>

namespace dlssnr {

enum class GeForceGeneration { Other, Rtx40, Rtx50 };

// Use the device selected by Vulkan. In particular, workstation names such as
// "NVIDIA RTX 4000 Ada Generation" must never select a GeForce model profile.
inline GeForceGeneration ModelGeneration(uint32_t vendor, std::string_view name) {
    if (vendor != 0x10de) return GeForceGeneration::Other;
    constexpr std::string_view manufacturer = "NVIDIA ";
    if (name.substr(0, manufacturer.size()) == manufacturer)
        name.remove_prefix(manufacturer.size());
    constexpr std::string_view prefix = "GeForce RTX ";
    if (name.substr(0, prefix.size()) != prefix) return GeForceGeneration::Other;
    name.remove_prefix(prefix.size());
    if (name.size() < 4 || (name[0] != '4' && name[0] != '5') || name[1] != '0' ||
        name[2] < '0' || name[2] > '9' || name[3] < '0' || name[3] > '9')
        return GeForceGeneration::Other;
    const auto suffix = name.substr(4);
    for (const auto accepted : {"", " Ti", " SUPER", " Ti SUPER", " Laptop GPU",
                                " Ti Laptop GPU", " SUPER Laptop GPU", "D", " D",
                                "D V2", " D V2"}) {
        if (suffix == accepted)
            return name[0] == '4' ? GeForceGeneration::Rtx40 : GeForceGeneration::Rtx50;
    }
    return GeForceGeneration::Other;
}

} // namespace dlssnr
