#!/bin/bash
set -e

echo "[1/4] Compiling Bare Host control binaries..."
gcc -O2 microbench/syscall_bench.c -o microbench/syscall_bench
gcc -O2 microbench/net_bench.c -o microbench/net_bench

echo "[2/4] Building shared Ubuntu 24.04 OCI image (Docker + gVisor)..."
docker build -f red_team/Dockerfile -t redteam-sandbox:latest .

echo "[3/4] Exporting identical image into Podman and containerd (nerdctl)..."
docker save redteam-sandbox:latest -o /tmp/redteam-sandbox.tar
podman load -i /tmp/redteam-sandbox.tar
sudo nerdctl load -i /tmp/redteam-sandbox.tar
rm -f /tmp/redteam-sandbox.tar

echo "[4/4] Syncing identical compiled binaries into LXC rootfs..."
docker rm -f tmp_extract >/dev/null 2>&1 || true
docker create --name tmp_extract redteam-sandbox:latest >/dev/null
rm -rf /tmp/rt_ext /tmp/mb_ext
docker cp tmp_extract:/red_team /tmp/rt_ext
docker cp tmp_extract:/microbench /tmp/mb_ext
docker rm tmp_extract >/dev/null

sudo rm -rf /var/lib/lxc/redteam-lxc/rootfs/red_team /var/lib/lxc/redteam-lxc/rootfs/microbench
sudo cp -r /tmp/rt_ext /var/lib/lxc/redteam-lxc/rootfs/red_team
sudo cp -r /tmp/mb_ext /var/lib/lxc/redteam-lxc/rootfs/microbench
rm -rf /tmp/rt_ext /tmp/mb_ext

echo "All 5 runtimes and Bare Host control binaries are synced."
