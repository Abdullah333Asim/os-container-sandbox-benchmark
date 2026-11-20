FROM ubuntu:24.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev util-linux procps && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /red_team
COPY cpu_virus.c io_virus.c mem_virus.c security_probes.sh run_virus.sh /red_team/

RUN gcc -O2 cpu_virus.c -o cpu_virus && \
    gcc -O2 io_virus.c -o io_virus && \
    gcc -O2 mem_virus.c -o mem_virus && \
    chmod +x /red_team/security_probes.sh /red_team/run_virus.sh

CMD ["/bin/bash"]
