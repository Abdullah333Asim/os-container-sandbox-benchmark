#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/time.h>

static inline double now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec * 1e9 + (double)ts.tv_nsec;
}

static int send_all(int fd, const void *buf, size_t len) {
    const char *p = (const char *)buf;
    while (len > 0) {
        ssize_t n = send(fd, p, len, 0);
        if (n <= 0) return -1;
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

static int recv_all(int fd, void *buf, size_t len) {
    char *p = (char *)buf;
    while (len > 0) {
        ssize_t n = recv(fd, p, len, 0);
        if (n <= 0) return -1;
        p += n;
        len -= (size_t)n;
    }
    return 0;
}

static int connect_host(const char *ip, int port, int nodelay) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct timeval tv = {5, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    if (nodelay) {
        int flag = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, ip, &addr.sin_addr) <= 0) {
        close(fd);
        return -1;
    }
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int run_server(int port) {
    signal(SIGPIPE, SIG_IGN);
    int sfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sfd < 0) return 1;

    int opt = 1;
    setsockopt(sfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons((uint16_t)port);

    if (bind(sfd, (struct sockaddr *)&addr, sizeof(addr)) < 0) return 1;
    if (listen(sfd, 16) < 0) return 1;

    char *bigbuf = malloc(65536);
    if (!bigbuf) return 1;

    while (1) {
        int cfd = accept(sfd, NULL, NULL);
        if (cfd < 0) continue;

        int flag = 1;
        setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

        char cmd = 0;
        if (recv_all(cfd, &cmd, 1) == 0) {
            if (cmd == 'R') {
                char pkt[64];
                while (recv_all(cfd, pkt, sizeof(pkt)) == 0) {
                    if (send_all(cfd, pkt, sizeof(pkt)) < 0) break;
                }
            } else if (cmd == 'T') {
                while (recv(cfd, bigbuf, 65536, 0) > 0) {}
                send_all(cfd, "OK", 2);
            }
        }
        close(cfd);
    }
    free(bigbuf);
    close(sfd);
    return 0;
}

static int run_client(const char *ip, int port) {
    signal(SIGPIPE, SIG_IGN);

    // 1. TCP Ping-Pong RTT (1000 x 64-byte round trips)
    double rtt_us = -1.0;
    int fd = connect_host(ip, port, 1);
    if (fd >= 0) {
        char cmd = 'R';
        char pkt[64];
        memset(pkt, 'P', sizeof(pkt));
        if (send_all(fd, &cmd, 1) == 0) {
            for (int i = 0; i < 50; i++) {
                send_all(fd, pkt, sizeof(pkt));
                recv_all(fd, pkt, sizeof(pkt));
            }
            const int n_rtt = 1000;
            double t0 = now_ns();
            int ok = 1;
            for (int i = 0; i < n_rtt; i++) {
                if (send_all(fd, pkt, sizeof(pkt)) < 0 ||
                    recv_all(fd, pkt, sizeof(pkt)) < 0) {
                    ok = 0;
                    break;
                }
            }
            double t1 = now_ns();
            if (ok) rtt_us = ((t1 - t0) / 1000.0) / n_rtt;
        }
        close(fd);
    }

    // 2. TCP Bulk Throughput (32 MB stream)
    double mb_s = -1.0;
    fd = connect_host(ip, port, 0);
    if (fd >= 0) {
        char cmd = 'T';
        char *chunk = malloc(65536);
        if (chunk) {
            memset(chunk, 'D', 65536);
            if (send_all(fd, &cmd, 1) == 0) {
                const int chunks = 512; // 512 * 64 KB = 32 MB
                double t0 = now_ns();
                int ok = 1;
                for (int i = 0; i < chunks; i++) {
                    if (send_all(fd, chunk, 65536) < 0) { ok = 0; break; }
                }
                shutdown(fd, SHUT_WR);
                char ack[2];
                if (ok && recv_all(fd, ack, 2) == 0) {
                    double t1 = now_ns();
                    double sec = (t1 - t0) / 1e9;
                    if (sec > 0.0) mb_s = 32.0 / sec;
                }
            }
            free(chunk);
        }
        close(fd);
    }

    // 3. Raw Socket Security Probe (SOCK_RAW ICMP)
    int rfd = socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
    const char *raw_status = "BLOCKED";
    char raw_detail[64];
    if (rfd >= 0) {
        close(rfd);
        raw_status = "EXPOSED";
        snprintf(raw_detail, sizeof(raw_detail), "raw_socket_created");
    } else {
        snprintf(raw_detail, sizeof(raw_detail), "errno_%d", errno);
    }

    printf("%.2f,%.2f,%s,%s\n", rtt_us, mb_s, raw_status, raw_detail);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc == 3 && strcmp(argv[1], "server") == 0) {
        return run_server(atoi(argv[2]));
    }
    if (argc == 4 && strcmp(argv[1], "client") == 0) {
        return run_client(argv[2], atoi(argv[3]));
    }
    fprintf(stderr, "Usage:\n  %s server <port>\n  %s client <host_ip> <port>\n", argv[0], argv[0]);
    return 1;
}
