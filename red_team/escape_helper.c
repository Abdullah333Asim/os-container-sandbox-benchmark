#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/ptrace.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <netinet/in.h>

int main(int argc, char *argv[]) {
    if (argc < 2) return 2;
    const char *test = argv[1];

    if (strcmp(test, "ptrace") == 0) {
        pid_t pid = fork();
        if (pid == 0) {
            pause();
            _exit(0);
        }
        usleep(50000);
        long rc = ptrace(PTRACE_ATTACH, pid, NULL, NULL);
        int err = errno;
        if (rc == 0) {
            waitpid(pid, NULL, 0);
            ptrace(PTRACE_DETACH, pid, NULL, NULL);
            kill(pid, SIGKILL);
            waitpid(pid, NULL, 0);
            printf("EXPOSED,ptrace_attach_succeeded\n");
        } else {
            kill(pid, SIGKILL);
            waitpid(pid, NULL, 0);
            printf("BLOCKED,errno_%d\n", err);
        }
        return 0;
    }

    if (strcmp(test, "bpf") == 0) {
        unsigned int attr[32];
        memset(attr, 0, sizeof(attr));
        attr[0] = 2; /* BPF_MAP_TYPE_ARRAY */
        attr[1] = 4; /* key_size */
        attr[2] = 4; /* value_size */
        attr[3] = 1; /* max_entries */
        long rc = syscall(SYS_bpf, 0, attr, sizeof(attr));
        if (rc >= 0) {
            close((int)rc);
            printf("EXPOSED,bpf_syscall_succeeded\n");
        } else {
            printf("BLOCKED,errno_%d\n", errno);
        }
        return 0;
    }

    if (strcmp(test, "sock_raw") == 0) {
        int fd = socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
        if (fd >= 0) {
            close(fd);
            printf("EXPOSED,raw_socket_created\n");
        } else {
            printf("BLOCKED,errno_%d\n", errno);
        }
        return 0;
    }

    if (strcmp(test, "chroot") == 0) {
        if (chroot("/tmp") == 0) {
            printf("EXPOSED,chroot_succeeded\n");
        } else {
            printf("BLOCKED,errno_%d\n", errno);
        }
        return 0;
    }

    if (strcmp(test, "keyctl") == 0) {
        long rc = syscall(SYS_keyctl, 0, -4, 0);
        if (rc >= 0) {
            printf("EXPOSED,keyctl_allowed\n");
        } else {
            printf("BLOCKED,errno_%d\n", errno);
        }
        return 0;
    }

    if (strcmp(test, "setns") == 0) {
        int fd = open("/proc/self/ns/mnt", O_RDONLY);
        if (fd < 0) {
            printf("BLOCKED,open_ns_errno_%d\n", errno);
            return 0;
        }
        int rc = (int)syscall(SYS_setns, fd, 0);
        int err = errno;
        close(fd);
        if (rc == 0) {
            printf("EXPOSED,setns_succeeded\n");
        } else {
            printf("BLOCKED,errno_%d\n", err);
        }
        return 0;
    }

    return 2;
}