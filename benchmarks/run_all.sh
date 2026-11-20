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
# PHASE 1: Cold-Start Latency & Idle Memory Footprint
# ----------------------------------------------------------------
echo "[Phase 1/5] Measuring startup latency & idle memory footprint..."
echo "runtime,trial,startup_ms,idle_ram_mb" > results/startup_overhead.csv

for rt in "${RUNTIMES[@]}"; do
    for t in $(seq 1 "$TRIALS"); do
        t0=$(date +%s%3N)
        case "$rt" in
            docker)     docker run --rm redteam-sandbox:latest /bin/true >/dev/null 2>&1 ;;
            podman)     run_podman run --rm docker.io/library/redteam-sandbox:latest /bin/true >/dev/null 2>&1 ;;
            containerd) nerdctl run --rm redteam-sandbox:latest /bin/true >/dev/null 2>&1 ;;
            gvisor)     docker run --rm --runtime=runsc redteam-sandbox:latest /bin/true >/dev/null 2>&1 ;;
            lxc)
                lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                lxc-start -n redteam-lxc >/dev/null 2>&1
                lxc-attach -n redteam-lxc -- /bin/true >/dev/null 2>&1
                ;;
        esac
        t1=$(date +%s%3N)
        startup_ms=$((t1 - t0))
        [ "$rt" = "lxc" ] && lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true

        # Measure idle RAM footprint
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
    done
done

# ----------------------------------------------------------------
# PHASE 2: Disk I/O & Syscall Overhead (32 MB synced write on /)
# ----------------------------------------------------------------
echo "[Phase 2/5] Measuring disk I/O & syscall overhead (32 MB fdatasync)..."
echo "runtime,trial,io_time_ms,throughput_mb_s" > results/io_overhead.csv

IO_CMD="dd if=/dev/zero of=/red_team/bench_io.dat bs=4k count=8192 conv=fdatasync 2>/dev/null && rm -f /red_team/bench_io.dat"

for rt in "${RUNTIMES[@]}"; do
    for t in $(seq 1 "$TRIALS"); do
        if [ "$rt" = "lxc" ]; then
            lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
            lxc-start -n redteam-lxc >/dev/null 2>&1
            sleep 1.5
            t0=$(date +%s%3N)
            lxc-attach -n redteam-lxc -- bash -c "$IO_CMD" >/dev/null 2>&1
            t1=$(date +%s%3N)
            lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
        else
            t0=$(date +%s%3N)
            case "$rt" in
                docker)     docker run --rm redteam-sandbox:latest bash -c "$IO_CMD" >/dev/null 2>&1 ;;
                podman)     run_podman run --rm docker.io/library/redteam-sandbox:latest bash -c "$IO_CMD" >/dev/null 2>&1 ;;
                containerd) nerdctl run --rm redteam-sandbox:latest bash -c "$IO_CMD" >/dev/null 2>&1 ;;
                gvisor)     docker run --rm --runtime=runsc redteam-sandbox:latest bash -c "$IO_CMD" >/dev/null 2>&1 ;;
            esac
            t1=$(date +%s%3N)
        fi
        io_ms=$((t1 - t0))
        mb_s=$(python3 -c "print(round(32.0 / max(${io_ms}/1000.0, 0.001), 2))")
        echo "${rt},${t},${io_ms},${mb_s}" >> results/io_overhead.csv
        echo "  disk_io | ${rt} trial ${t}: ${io_ms} ms (${mb_s} MB/s)"
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
# PHASE 4: Idle Host Ground-Truth Baseline
# ----------------------------------------------------------------
echo "[Phase 4/5] Measuring idle host Ground Truth baseline (10s)..."
python3 blue_team/host_workload.py --duration 10 --out results/host_baseline.json
BASE_OPS=$(python3 -c "import json; print(json.load(open('results/host_baseline.json'))['throughput_ops_sec'])")
BASE_MS=$(python3 -c "import json; print(json.load(open('results/host_baseline.json'))['mean_ms'])")
echo "  host baseline: ${BASE_OPS} ops/sec (mean loop ${BASE_MS} ms)"

# ----------------------------------------------------------------
# PHASE 5: Red Team vs. Blue Team Arena
# ----------------------------------------------------------------
echo "[Phase 5/5] Running Red Team vs. Blue Team arena..."
echo "runtime,virus,gen,trial,detected,trigger,mttd_ms,containment_ms,total_response_ms,peak_cpu_pct,peak_mem_mb,peak_io_mb,inner_proc_visible,host_mean_ms,host_utility_pct" > results/arena_results.csv

for rt in "${RUNTIMES[@]}"; do
    for virus in "${VIRUSES[@]}"; do
        for gen in "${GENS[@]}"; do
            for t in $(seq 1 "$TRIALS"); do
                cname="arena-ctr"
                [ "$rt" = "lxc" ] && cname="redteam-lxc"
                cleanup_ctr "$rt" "$cname"

                # Start innocent Host Ground Truth workload in background
                rm -f /tmp/host_trial.json /tmp/bt_trial.json
                python3 blue_team/host_workload.py --duration 25 --out /tmp/host_trial.json &
                HOST_PID=$!

                # Launch Red Team container
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

                # Run Blue Team monitor (15s cap handles Gen 2/3 mem_virus cleanly)
                python3 blue_team/blue_team_monitor.py \
                    --runtime "$rt" \
                    --container "$cname" \
                    --podman-user "$REAL_USER" \
                    --timeout 15 \
                    --out /tmp/bt_trial.json >/dev/null

                # Stop Host Ground Truth workload & wait for JSON flush
                kill -TERM "$HOST_PID" 2>/dev/null || true
                wait "$HOST_PID" 2>/dev/null || true
                cleanup_ctr "$rt" "$cname"

                # Append one clean CSV row
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
