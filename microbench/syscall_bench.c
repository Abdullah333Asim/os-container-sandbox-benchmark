#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <sys/syscall.h>
#include <sys/mman.h>
#include <sys/wait.h>

static inline double now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1e9 + (double)ts.tv_nsec;
}

int main(void) {
    double t0, t1;

    // 1. Pure syscall transition: SYS_getpid
    const int n_getpid = 50000;
    t0 = now_ns();
    for (int i = 0; i < n_getpid; i++) {
        volatile long pid = syscall(SYS_getpid);
        (void)pid;
    }
    t1 = now_ns();
    printf("getpid,%d,%.2f\n", n_getpid, (t1 - t0) / n_getpid);

    // 2. VFS path lookup & FD allocation: open + close /dev/null
    const int n_open = 10000;
    t0 = now_ns();
    for (int i = 0; i < n_open; i++) {
        int fd = open("/dev/null", O_RDONLY);
        if (fd >= 0) close(fd);
    }
    t1 = now_ns();
    printf("open_close,%d,%.2f\n", n_open, (t1 - t0) / n_open);

    // 3. IPC round-trip: pipe write + read (1 byte)
    const int n_pipe = 20000;
    int pfd[2];
    if (pipe(pfd) == 0) {
        char c = 'x';
        t0 = now_ns();
        for (int i = 0; i < n_pipe; i++) {
            if (write(pfd[1], &c, 1) != 1) break;
            if (read(pfd[0], &c, 1) != 1) break;
        }
        t1 = now_ns();
        close(pfd[0]);
        close(pfd[1]);
        printf("pipe_rw,%d,%.2f\n", n_pipe, (t1 - t0) / n_pipe);
    }

    // 4. Virtual memory: mmap 4KB + minor page fault + munmap
    const int n_mmap = 10000;
    t0 = now_ns();
    for (int i = 0; i < n_mmap; i++) {
        void *p = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (p != MAP_FAILED) {
            ((volatile char *)p)[0] = 1;
            munmap(p, 4096);
        }
    }
    t1 = now_ns();
    printf("mmap_fault_unmap,%d,%.2f\n", n_mmap, (t1 - t0) / n_mmap);

    // 5. Process creation & scheduling: fork + _exit + waitpid
    const int n_fork = 200;
    t0 = now_ns();
    for (int i = 0; i < n_fork; i++) {
        pid_t pid = fork();
        if (pid == 0) {
            _exit(0);
        } else if (pid > 0) {
            waitpid(pid, NULL, 0);
        }
    }
    t1 = now_ns();
    printf("fork_wait,%d,%.2f\n", n_fork, (t1 - t0) / n_fork);

    return 0;
}
