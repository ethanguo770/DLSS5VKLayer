#define _POSIX_C_SOURCE 200809L
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* A desktop-launchable ELF entry point; no AppImage runtime or FUSE needed. */
int main(int argc, char **argv) {
    char executable[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length <= 0 || length >= (ssize_t)sizeof(executable) - 1) {
        fputs("Cannot locate the DLSSNR package.\n", stderr);
        return 1;
    }
    executable[length] = '\0';
    char *separator = strrchr(executable, '/');
    if (!separator) return 1;
    *separator = '\0';
    char script[PATH_MAX];
    int size = snprintf(script, sizeof(script), "%s/start-dlssnr.sh", executable);
    if (size < 0 || (size_t)size >= sizeof(script)) return 1;
    char **arguments = calloc((size_t)argc + 2, sizeof(char *));
    if (!arguments) return 1;
    arguments[0] = "bash";
    arguments[1] = script;
    for (int i = 1; i < argc; ++i) arguments[i + 1] = argv[i];
    execv("/bin/bash", arguments);
    perror("Cannot start DLSSNR");
    free(arguments);
    return 1;
}
