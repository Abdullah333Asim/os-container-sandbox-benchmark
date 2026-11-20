#!/bin/bash
set -u

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./benchmarks/run_all.sh [trials]"
    exit 1
fi

TRIALS="${1:-3}"
REAL_USER="${SUDO_USER:-$USER}"
REAL_UID=$(id -u "$REAL_USER")
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
HOST_K=$(uname -r)

RUNTIMES=("docker" "podman" "containerd" "gvisor" "lxc")
VIRUSES=("cpu_virus" "mem_virus" "io_virus")
GENS=(1 2 3)

mkdir -p results/figures
rm -f results/startup_overhead.csv results/io_overhead.csv results/security_probes.csv results/arena_results.csv

run_podman() {
    sudo -u "$REAL_USER" env XDG_RUNTIME_DIR="/run/user/${REAL_UID}" HOME="${REAL_HOME}" podman "$@"
}

time_ms() {
    python3 -c '
import subprocess, sys, time
t0 = time.perf_counter()
subprocess.run(sys.argv[1:], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(int((time.perf_counter() - t0) * 1000))
' "$@"
}

cleanup_ctr() {
    local rt="$1"
    local name="$2"
    case "$rt" in
        docker|gvisor) docker rm -f "$name" >/dev/null 2>&1 || true ;;
        podman) run_podman rm -f "$name" >/dev/null 2>&1 || true ;;
        containerd) nerdctl rm -f "$name" >/dev/null 2>&1 || true ;;
        lxc)
            lxc-stop -k -n "$name" >/dev/null 2>&1 || true
            rm -rf "/var/lib/lxc/${name}/rootfs/tmp/os_arena" "/var/lib/lxc/${name}/rootfs/red_team/bench_io.dat" 2>/dev/null || true
            ;;
    esac
}

echo "================================================================"
echo " OS CONTAINER SANDBOX BENCHMARK (TRIALS=${TRIALS}, USER=${REAL_USER})"
echo "================================================================"

# ----------------------------------------------------------------
# PHASE 1: Cold-Start Latency (Monotonic) & Idle Memory Footprint
# ----------------------------------------------------------------
echo "[Phase 1/5] Measuring startup latency & idle memory footprint..."
echo "runtime,trial,startup_ms,idle_ram_mb" > results/startup_overhead.csv

declare -A IDLE_RAM_MAP

for rt in "${RUNTIMES[@]}"; do
    ram_sum=0
    for t in $(seq 1 "$TRIALS"); do
        case "$rt" in
            docker)
                startup_ms=$(time_ms docker run --rm redteam-sandbox:latest /bin/true)
                ;;
            podman)
                startup_ms=$(time_ms sudo -u "$REAL_USER" env XDG_RUNTIME_DIR="/run/user/${REAL_UID}" HOME="${REAL_HOME}" podman run --rm docker.io/library/redteam-sandbox:latest /bin/true)
                ;;
            containerd)
                startup_ms=$(time_ms nerdctl run --rm redteam-sandbox:latest /bin/true)
                ;;
            gvisor)
                startup_ms=$(time_ms docker run --rm --runtime=runsc redteam-sandbox:latest /bin/true)
                ;;
            lxc)
                lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                startup_ms=$(time_ms bash -c "lxc-start -n redteam-lxc && lxc-attach -n redteam-lxc -- /bin/true")
                lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                ;;
        esac

        cname="idle-bench"
        [ "$rt" = "lxc" ] && cname="redteam-lxc"
        cleanup_ctr "$rt" "$cname"
        case "$rt" in
            docker)     docker run -d --name "$cname" redteam-sandbox:latest sleep 10 >/dev/null 2>&1 ;;
            podman)     run_podman run -d --name "$cname" docker.io/library/redteam-sandbox:latest sleep 10 >/dev/null 2>&1 ;;
            containerd) nerdctl run -d --name "$cname" redteam-sandbox:latest sleep 10 >/dev/null 2>&1 ;;
            gvisor)     docker run -d --runtime=runsc --name "$cname" redteam-sandbox:latest sleep 10 >/dev/null 2>&1 ;;
            lxc)        lxc-start -n redteam-lxc >/dev/null 2>&1 ;;
        esac
        sleep 1.2
        idle_ram=$(python3 - "$rt" "$cname" "$REAL_USER" << 'PYEOF'
import sys, psutil
sys.path.insert(0, "blue_team")
import blue_team_monitor as btm
rt, cname, user = sys.argv[1], sys.argv[2], sys.argv[3]
rpid = btm.get_root_pid(rt, cname, user)
pids = btm.get_container_pids(rt, rpid)
rss = 0.0
for p in pids:
    try:
        rss += psutil.Process(p).memory_info().rss / (1024 * 1024)
    except Exception:
        pass
print(f"{rss:.2f}")
PYEOF
)
        cleanup_ctr "$rt" "$cname"
        echo "${rt},${t},${startup_ms},${idle_ram}" >> results/startup_overhead.csv
        echo "  startup | ${rt} trial ${t}: ${startup_ms} ms, idle RAM ${idle_ram} MB"
        ram_sum=$(python3 -c "print(${ram_sum} + ${idle_ram})")
    done
    IDLE_RAM_MAP[$rt]=$(python3 -c "print(round(${ram_sum} / ${TRIALS}, 2))")
done

# ----------------------------------------------------------------
# PHASE 2: Syscall-Heavy Disk I/O Overhead (Timed INSIDE container)
# ----------------------------------------------------------------
echo "[Phase 2/5] Measuring inside-container disk I/O & syscall overhead (32,768 x 512B fdatasync)..."
echo "runtime,trial,io_time_ms,throughput_mb_s" > results/io_overhead.csv

IO_CMD="dd if=/dev/zero of=/red_team/bench_io.dat bs=512 count=32768 conv=fdatasync 2>&1; rm -f /red_team/bench_io.dat"

for rt in "${RUNTIMES[@]}"; do
    for t in $(seq 1 "$TRIALS"); do
        case "$rt" in
            docker)     dd_out=$(docker run --rm redteam-sandbox:latest bash -c "$IO_CMD") ;;
            podman)     dd_out=$(run_podman run --rm docker.io/library/redteam-sandbox:latest bash -c "$IO_CMD") ;;
            containerd) dd_out=$(nerdctl run --rm redteam-sandbox:latest bash -c "$IO_CMD") ;;
            gvisor)     dd_out=$(docker run --rm --runtime=runsc redteam-sandbox:latest bash -c "$IO_CMD") ;;
            lxc)
                lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                lxc-start -n redteam-lxc >/dev/null 2>&1
                sleep 1.5
                dd_out=$(lxc-attach -n redteam-lxc -- bash -c "$IO_CMD")
                lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                ;;
        esac
        parsed=$(python3 - "$dd_out" << 'PYEOF'
import re, sys
txt = sys.argv[1]
m = re.search(r"copied,\s+([0-9.]+)\s+s", txt)
sec = float(m.group(1)) if m else 1.0
io_ms = round(sec * 1000.0, 2)
mb_s = round(16.0 / max(sec, 0.0001), 2)
print(f"{io_ms},{mb_s}")
PYEOF
)
        echo "${rt},${t},${parsed}" >> results/io_overhead.csv
        echo "  disk_io | ${rt} trial ${t}: ${parsed} (ms, MB/s)"
    done
done

# ----------------------------------------------------------------
# PHASE 3: Security Isolation Probes
# ----------------------------------------------------------------
echo "[Phase 3/5] Running security isolation probes across all 5 runtimes..."
echo "runtime,probe,status,detail" > results/security_probes.csv

for rt in "${RUNTIMES[@]}"; do
    case "$rt" in
        docker)     out=$(docker run --rm redteam-sandbox:latest /red_team/security_probes.sh "$HOST_K") ;;
        podman)     out=$(run_podman run --rm docker.io/library/redteam-sandbox:latest /red_team/security_probes.sh "$HOST_K") ;;
        containerd) out=$(nerdctl run --rm redteam-sandbox:latest /red_team/security_probes.sh "$HOST_K") ;;
        gvisor)     out=$(docker run --rm --runtime=runsc redteam-sandbox:latest /red_team/security_probes.sh "$HOST_K") ;;
        lxc)
            lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
            lxc-start -n redteam-lxc >/dev/null 2>&1
            sleep 1.5
            out=$(lxc-attach -n redteam-lxc -- /red_team/security_probes.sh "$HOST_K")
            lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
            ;;
    esac
    while IFS= read -r line; do
        [ -n "$line" ] && echo "${rt},${line}" >> results/security_probes.csv
    done <<< "$out"
    echo "  probes  | ${rt}: $(echo "$out" | grep '^SUMMARY')"
done

# ----------------------------------------------------------------
# PHASE 4: Idle Host Ground-Truth Baseline (2s warmup + 10s measure)
# ----------------------------------------------------------------
echo "[Phase 4/5] Measuring idle host Ground Truth baseline (2s warmup + 10s)..."
python3 blue_team/host_workload.py --warmup 2 --duration 10 --out results/host_baseline.json
BASE_OPS=$(python3 -c "import json; print(json.load(open('results/host_baseline.json'))['throughput_ops_sec'])")
BASE_MS=$(python3 -c "import json; print(json.load(open('results/host_baseline.json'))['mean_ms'])")
echo "  host baseline: ${BASE_OPS} ops/sec (mean loop ${BASE_MS} ms)"

# ----------------------------------------------------------------
# PHASE 5: Red Team vs. Blue Team Arena
# ----------------------------------------------------------------
echo "[Phase 5/5] Running Red Team vs. Blue Team arena..."
echo "runtime,virus,gen,trial,detected,trigger,mttd_ms,containment_ms,total_response_ms,peak_cpu_pct,peak_mem_mb,peak_io_mb,inner_proc_visible,host_mean_ms,host_utility_pct" > results/arena_results.csv

for rt in "${RUNTIMES[@]}"; do
    base_mem="${IDLE_RAM_MAP[$rt]}"
    for virus in "${VIRUSES[@]}"; do
        for gen in "${GENS[@]}"; do
            for t in $(seq 1 "$TRIALS"); do
                cname="arena-ctr"
                [ "$rt" = "lxc" ] && cname="redteam-lxc"
                cleanup_ctr "$rt" "$cname"

                rm -f /tmp/host_trial.json /tmp/bt_trial.json
                python3 blue_team/host_workload.py --duration 25 --out /tmp/host_trial.json &
                HOST_PID=$!

                case "$rt" in
                    docker)
                        docker run -d --name "$cname" redteam-sandbox:latest /red_team/run_virus.sh "$virus" "$gen" >/dev/null 2>&1
                        ;;
                    podman)
                        run_podman run -d --name "$cname" docker.io/library/redteam-sandbox:latest /red_team/run_virus.sh "$virus" "$gen" >/dev/null 2>&1
                        ;;
                    containerd)
                        nerdctl run -d --name "$cname" redteam-sandbox:latest /red_team/run_virus.sh "$virus" "$gen" >/dev/null 2>&1
                        ;;
                    gvisor)
                        docker run -d --runtime=runsc --name "$cname" redteam-sandbox:latest /red_team/run_virus.sh "$virus" "$gen" >/dev/null 2>&1
                        ;;
                    lxc)
                        lxc-start -n redteam-lxc >/dev/null 2>&1
                        sleep 1.5
                        lxc-attach -n redteam-lxc -- /red_team/run_virus.sh "$virus" "$gen" >/dev/null 2>&1 &
                        ;;
                esac

                python3 blue_team/blue_team_monitor.py \
                    --runtime "$rt" \
                    --container "$cname" \
                    --podman-user "$REAL_USER" \
                    --base-mem-mb "$base_mem" \
                    --mem-thresh-mb 150.0 \
                    --timeout 15 \
                    --out /tmp/bt_trial.json >/dev/null

                kill -TERM "$HOST_PID" 2>/dev/null || true
                wait "$HOST_PID" 2>/dev/null || true
                cleanup_ctr "$rt" "$cname"

                row=$(python3 - "$rt" "$virus" "$gen" "$t" "$BASE_OPS" << 'PYEOF'
import json, sys
rt, virus, gen, trial, base_ops = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[5])
bt = json.load(open("/tmp/bt_trial.json"))
hw = json.load(open("/tmp/host_trial.json"))
util = min(100.0, round((hw["throughput_ops_sec"] / base_ops) * 100.0, 2)) if base_ops > 0 else 0.0
print(f"{rt},{virus},{gen},{trial},{bt['detected']},{bt['trigger']},{bt['mttd_ms']},{bt['containment_ms']},{bt['total_response_ms']},{bt['peak_cpu_pct']},{bt['peak_mem_mb']},{bt['peak_io_mb']},{bt['inner_proc_visible']},{hw['mean_ms']},{util}")
PYEOF
)
                echo "$row" >> results/arena_results.csv
                echo "  arena   | ${rt} | ${virus} G${gen} T${t} -> ${row}"
            done
        done
    done
done

chown -R "${REAL_USER}:${REAL_USER}" results/
echo "================================================================"
echo " BENCHMARK COMPLETE! Raw CSVs saved in results/"
echo "================================================================"
