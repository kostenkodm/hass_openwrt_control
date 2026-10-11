/* SPDX-License-Identifier: MIT
 * Root-only plumbing. Never exported through ubus. Arguments are constructed
 * by platform.uc from fixed commands and locally provisioned configuration.
 */
#define _GNU_SOURCE
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static volatile sig_atomic_t running_child;
static void terminate(int sig) {
    if (running_child > 0) kill(-running_child, SIGKILL);
    _exit(128 + sig);
}
static int syncpath(const char *p) {
    int f = open(p, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (f < 0) return 1;
    int r = fsync(f); close(f); return r ? 1 : 0;
}
static int same(int a, int b) {
    char x[8192], y[8192]; ssize_t n, m;
    lseek(a, 0, SEEK_SET); lseek(b, 0, SEEK_SET);
    do {
        n = read(a, x, sizeof(x)); m = read(b, y, sizeof(y));
        if (n < 0 || m < 0 || n != m || (n && memcmp(x, y, n))) return 0;
    } while (n);
    return 1;
}
static int replace(const char *path, const char *expected, const char *next) {
    int f = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    int e = open(expected, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    int n = open(next, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat st, current;
    int rc = 1;
    if (f < 0 || e < 0 || n < 0 || flock(f, LOCK_EX)) goto done;
    /* libuci also uses flock. A writer which opened the old inode before our
     * rename is still a residual race: see docs/podkop-controller.ru.md. */
    if (fstat(f, &st) || lstat(path, &current) || st.st_ino != current.st_ino ||
        st.st_dev != current.st_dev || !same(f, e)) { rc = 3; goto done; }
    if (fsync(n) || chmod(next, st.st_mode & 0777) || rename(next, path)) goto done;
    char *parent = strdup(path), *slash = strrchr(parent, '/');
    if (!slash) { free(parent); goto done; }
    *slash = 0; rc = syncpath(parent); free(parent);
done:
    if (f >= 0) close(f);
    if (e >= 0) close(e);
    if (n >= 0) close(n);
    return rc;
}
static int run(int argc, char **argv) {
    if (argc < 5) return 2;
    int ms = atoi(argv[2]);
    if (ms < 1 || ms > 300000) return 2;
    int out = open(argv[3], O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (out < 0) return 1;
    pid_t child = fork();
    if (child < 0) { close(out); return 1; }
    if (!child) {
        setpgid(0, 0);
        struct rlimit output_limit = {1048576, 1048576};
        setrlimit(RLIMIT_FSIZE, &output_limit);
        prctl(PR_SET_PDEATHSIG, SIGKILL);
        dup2(out, 1); dup2(out, 2); close(out);
        execv(argv[4], &argv[4]); _exit(127);
    }
    close(out); running_child = child; setpgid(child, child);
    struct timespec wait = {0, 10000000}; int status;
    for (int elapsed = 0; elapsed < ms; elapsed += 10) {
        if (waitpid(child, &status, WNOHANG) == child)
            return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
        nanosleep(&wait, NULL);
    }
    kill(-child, SIGKILL); waitpid(child, &status, 0); return 124;
}
int main(int argc, char **argv) {
    pid_t parent = getppid();
    signal(SIGTERM, terminate); signal(SIGINT, terminate);
    prctl(PR_SET_PDEATHSIG, SIGTERM);
    if (getppid() != parent) return 1;
    if (argc == 3 && !strcmp(argv[1], "sync")) return syncpath(argv[2]);
    if (argc == 5 && !strcmp(argv[1], "replace")) return replace(argv[2], argv[3], argv[4]);
    if (argc > 4 && !strcmp(argv[1], "run")) return run(argc, argv);
    return 2;
}
