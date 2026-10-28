/*
 * launcher.c: the helper app's main executable.
 *
 * LaunchServices needs a real Mach-O binary as an app's main executable (a shell
 * script will not do, and AppleScript applets cannot receive --args). This tiny
 * launcher finds Contents/Resources/worker.sh next to itself and execs it with
 * the arguments it was given, so
 *     open -n -a FoundryPhone.app --args tap 10 20
 * becomes
 *     /bin/bash .../Contents/Resources/worker.sh tap 10 20
 * running as the helper app, which holds the TCC grants.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <limits.h>
#include <libgen.h>
#include <mach-o/dyld.h>

int main(int argc, char **argv) {
    char exe[PATH_MAX];
    uint32_t sz = sizeof(exe);
    if (_NSGetExecutablePath(exe, &sz) != 0) return 71;
    char real[PATH_MAX];
    if (!realpath(exe, real)) { strncpy(real, exe, sizeof(real) - 1); real[sizeof(real) - 1] = 0; }
    char *macos = dirname(real); /* .../Contents/MacOS */
    char worker[PATH_MAX];
    snprintf(worker, sizeof(worker), "%s/../Resources/worker.sh", macos);

    char **nv = calloc((size_t)argc + 3, sizeof(char *));
    if (!nv) return 70;
    int n = 0;
    nv[n++] = "/bin/bash";
    nv[n++] = worker;
    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "-psn", 4) == 0) continue; /* legacy LaunchServices arg */
        nv[n++] = argv[i];
    }
    nv[n] = NULL;
    execv("/bin/bash", nv);
    perror("execv");
    return 127;
}
