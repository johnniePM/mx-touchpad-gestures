/* Small, low-latency Solaar Execute action; no Python process per click.
 * Sends one fixed press/release datagram to the existing unprivileged daemon.
 * Build locally: cc -O2 -Wall -Wextra -std=c11 -o mxmaster3-gesture-signal fast_signal.c
 * License: AGPL-3.0-only.
 */
#define _POSIX_C_SOURCE 200809L
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "press") != 0 && strcmp(argv[1], "release") != 0)) {
        fprintf(stderr, "Usage: mxmaster3-gesture-signal press|release\n");
        return 2;
    }
    const char *dir = getenv("XDG_RUNTIME_DIR");
    char fallback[64];
    if (dir == NULL || dir[0] == '\0') {
        int n = snprintf(fallback, sizeof fallback, "/run/user/%lu", (unsigned long) getuid());
        if (n < 0 || (size_t)n >= sizeof fallback) return 1;
        dir = fallback;
    }
    struct stat st;
    if (stat(dir, &st) < 0 || !S_ISDIR(st.st_mode) || st.st_uid != getuid() || (st.st_mode & 0077) != 0) {
        fprintf(stderr, "Invalid/private XDG runtime directory required\n");
        return 1;
    }
    struct sockaddr_un target = {0};
    target.sun_family = AF_UNIX;
    int length = snprintf(target.sun_path, sizeof target.sun_path, "%s/%s",
                          dir, "mxmaster3-gestures-control.sock");
    if (length < 0 || (size_t)length >= sizeof target.sun_path) {
        fprintf(stderr, "Socket path too long\n");
        return 1;
    }
    int sock = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (sock < 0) { perror("socket"); return 1; }
    size_t bytes = strlen(argv[1]);
    ssize_t sent = sendto(sock, argv[1], bytes, 0, (struct sockaddr *)&target,
                          (socklen_t)(offsetof(struct sockaddr_un, sun_path) + length + 1));
    int failed = sent != (ssize_t) bytes;
    if (failed) perror("sendto: start MX Master 3 Gestures first");
    close(sock);
    return failed ? 1 : 0;
}
