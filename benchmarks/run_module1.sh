#!/bin/bash
set -u

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./benchmarks/run_module1.sh [trials]"
    exit 1
fi

TRIALS="${1:-5}"
REAL_USER="${SUDO_USER:-$USER}"
REAL_UID=$(id -u "$REAL_USER")
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
PORT=18888

# Detect primary non-loopback IPv4 address of the host VM
HOST_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
if [ -z "$HOST_IP" ]; then
    HOST_IP=$(hostname -I | awk '{print $1}')
fi

RUNTIMES=("host" "docker" "podman" "containerd" "gvisor" "lxc")

mkdir -p results
echo "runtime,trial,operation,iterations,ns_per_op" > results/syscall_bench.csv
echo "runtime,trial,tcp_rtt_us,tcp_throughput_mb_s,sock_raw_status,sock_raw_detail" > results/net_bench.csv

run_podman() {
    sudo -u "$REAL_USER" env XDG_RUNTIME_DIR="/run/user/${REAL_UID}" HOME="${REAL_HOME}" podman "$@"
}

echo "================================================================"
echo " MODULE 1: SYSCALL & NETWORK MICROBENCHMARKS (TRIALS=${TRIALS})"
echo " Host VM IP: ${HOST_IP} | Server Port: ${PORT}"
echo "================================================================"

# ----------------------------------------------------------------
# PART A: C Syscall Microbenchmark Suite
# ----------------------------------------------------------------
echo "[Part A] Running syscall_bench across Bare Host + 5 runtimes..."

for rt in "${RUNTIMES[@]}"; do
    if [ "$rt" = "lxc" ]; then
        lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
        lxc-start -n redteam-lxc >/dev/null 2>&1
        sleep 2
    fi

    for t in $(seq 1 "$TRIALS"); do
        case "$rt" in
            host)       out=$(./microbench/syscall_bench) ;;
            docker)     out=$(docker run --rm redteam-sandbox:latest /microbench/syscall_bench) ;;
            podman)     out=$(run_podman run --rm docker.io/library/redteam-sandbox:latest /microbench/syscall_bench) ;;
            containerd) out=$(nerdctl run --rm redteam-sandbox:latest /microbench/syscall_bench) ;;
            gvisor)     out=$(docker run --rm --runtime=runsc redteam-sandbox:latest /microbench/syscall_bench) ;;
            lxc)        out=$(lxc-attach -n redteam-lxc -- /microbench/syscall_bench) ;;
        esac
        while IFS= read -r line; do
            [ -n "$line" ] && echo "${rt},${t},${line}" >> results/syscall_bench.csv
        done <<< "$out"
        echo "  syscall | ${rt} trial ${t} done"
    done

    [ "$rt" = "lxc" ] && lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
done

# ----------------------------------------------------------------
# PART B: Container-to-Host Network Stack & SOCK_RAW Benchmark
# ----------------------------------------------------------------
echo "[Part B] Starting host TCP benchmark server on 0.0.0.0:${PORT}..."
./microbench/net_bench server "$PORT" &
SRV_PID=$!
trap 'kill "$SRV_PID" 2>/dev/null || true' EXIT
sleep 0.5

for rt in "${RUNTIMES[@]}"; do
    TARGET_IP="$HOST_IP"
    [ "$rt" = "host" ] && TARGET_IP="127.0.0.1"

    if [ "$rt" = "lxc" ]; then
        lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
        lxc-start -n redteam-lxc >/dev/null 2>&1
        # Wait up to 8s for LXC DHCP IP on eth0
        for _ in $(seq 1 16); do
            if lxc-attach -n redteam-lxc -- ip -4 addr show eth0 2>/dev/null | grep -q "inet "; then
                break
            fi
            sleep 0.5
        done
    fi

    for t in $(seq 1 "$TRIALS"); do
        case "$rt" in
            host)       out=$(./microbench/net_bench client "$TARGET_IP" "$PORT") ;;
            docker)     out=$(docker run --rm redteam-sandbox:latest /microbench/net_bench client "$TARGET_IP" "$PORT") ;;
            podman)     out=$(run_podman run --rm docker.io/library/redteam-sandbox:latest bash -c 'read -r GW _ <<< "$(getent ahostsv4 host.containers.internal)"; /microbench/net_bench client "$GW" "$1"' _ "$PORT") ;;
            containerd) out=$(nerdctl run --rm redteam-sandbox:latest /microbench/net_bench client "$TARGET_IP" "$PORT") ;;
            gvisor)     out=$(docker run --rm --runtime=runsc redteam-sandbox:latest /microbench/net_bench client "$TARGET_IP" "$PORT") ;;
            lxc)        out=$(lxc-attach -n redteam-lxc -- /microbench/net_bench client "$TARGET_IP" "$PORT") ;;
        esac
        echo "${rt},${t},${out}" >> results/net_bench.csv
        echo "  network | ${rt} trial ${t} -> ${out}"
    done

    [ "$rt" = "lxc" ] && lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
done

kill "$SRV_PID" 2>/dev/null || true
chown -R "${REAL_USER}:${REAL_USER}" results/
echo "================================================================"
echo " MODULE 1 COMPLETE! Saved results/syscall_bench.csv & net_bench.csv"
echo "================================================================"
