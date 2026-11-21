#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <sys/wait.h>

int main(int argc, char *argv[]) {
    int target = (argc >= 2) ? atoi(argv[1]) : 500;
    if (target < 1) target = 1;
    if (target > 2000) target = 2000;

    pid_t *pids = calloc((size_t)target, sizeof(pid_t));
    if (!pids) return 1;

    int spawned = 0;
    int fail_errno = 0;

    for (int i = 0; i < target; i++) {
        pid_t p = fork();
        if (p == 0) {
            pause();
            _exit(0);
        } else if (p > 0) {
            pids[spawned++] = p;
        } else {
            fail_errno = errno;
            break;
        }
    }

    usleep(500000);

    for (int i = 0; i < spawned; i++) {
        kill(pids[i], SIGKILL);
    }
    for (int i = 0; i < spawned; i++) {
        waitpid(pids[i], NULL, 0);
    }

    free(pids);
    printf("FORK_RESULT,%d,%d,%d\n", target, spawned, fail_errno);
    return 0;
}