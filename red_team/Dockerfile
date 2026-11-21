FROM ubuntu:24.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev util-linux procps iproute2 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /red_team
COPY red_team/cpu_virus.c red_team/io_virus.c red_team/mem_virus.c \
     red_team/stress_virus.c red_team/fork_bomb.c red_team/escape_helper.c \
     red_team/security_probes.sh red_team/escape_suite_v2.sh red_team/run_virus.sh /red_team/
RUN gcc -O2 cpu_virus.c -o cpu_virus && \
    gcc -O2 io_virus.c -o io_virus && \
    gcc -O2 mem_virus.c -o mem_virus && \
    gcc -O2 -pthread stress_virus.c -o stress_virus && \
    gcc -O2 fork_bomb.c -o fork_bomb && \
    gcc -O2 escape_helper.c -o escape_helper && \
    chmod +x /red_team/security_probes.sh /red_team/escape_suite_v2.sh /red_team/run_virus.sh

WORKDIR /microbench
COPY microbench/syscall_bench.c microbench/net_bench.c /microbench/
RUN gcc -O2 syscall_bench.c -o syscall_bench && \
    gcc -O2 net_bench.c -o net_bench

WORKDIR /red_team
CMD ["/bin/bash"]