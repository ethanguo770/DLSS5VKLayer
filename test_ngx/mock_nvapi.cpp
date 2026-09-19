#include <windows.h>

// Test-only DLL. It must never be included in a runtime package.
extern "C" __declspec(dllexport) unsigned int DlssnrTestNvapiMarker() {
    return 0x4e565041;
}
