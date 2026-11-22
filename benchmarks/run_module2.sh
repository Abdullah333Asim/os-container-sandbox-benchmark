#!/bin/bash
set -u

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo ./benchmarks/run_module2.sh [trials]"
    exit 1
fi

TRIALS="${1:-3}"
REAL_USER="${SUDO_USER:-$USER}"
REAL_UID=$(id -u "$REAL_USER")
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
HOST_K=$(uname -r)

RUNTIMES=("docker" "podman" "containerd" "gvisor" "lxc")
CANARY_DIR="/tmp/host_canary_dir"

mkdir -p results
echo "runtime,probe,status,detail" > results/module2_escapes.csv
echo "runtime,mode,trial,target_pids,spawned_pids,fail_errno,exit_code,outcome" > results/module2_forkbomb.csv
echo "runtime,mode,trial,host_mean_ms,host_ops_sec,host_utility_pct" > results/module2_starvation.csv

run_podman() {
    sudo -u "$REAL_USER" env XDG_RUNTIME_DIR="/run/user/${REAL_UID}" HOME="${REAL_HOME}" podman "$@"
}

cleanup_ctr() {
    local rt="$1"
    local name="$2"
    case "$rt" in
        docker|gvisor) docker rm -f "$name" >/dev/null 2>&1 || true ;;
        podman)        run_podman rm -f "$name" >/dev/null 2>&1 || true ;;
        containerd)    nerdctl rm -f "$name" >/dev/null 2>&1 || true ;;
        lxc)           lxc-stop -k -n "$name" >/dev/null 2>&1 || true ;;
    esac
}

echo "================================================================"
echo " MODULE 2: ESCAPES v2, FORK-BOMB & STARVATION (TRIALS=${TRIALS})"
echo " Host Kernel: ${HOST_K}"
echo "================================================================"

# ----------------------------------------------------------------
# PART A: 15-Test Active Escape & Privilege Audit Suite v2
# ----------------------------------------------------------------
echo "[Part A] Running 15-test Active Escape Suite v2 across all 5 runtimes..."
rm -rf "$CANARY_DIR"
mkdir -p "$CANARY_DIR"
chmod 0755 "$CANARY_DIR"
echo "HOST_CANARY_SECRET_2026" > "${CANARY_DIR}/host_secret.txt"
chown root:root "${CANARY_DIR}/host_secret.txt"
chmod 0600 "${CANARY_DIR}/host_secret.txt"
mkdir -p /var/lib/lxc/redteam-lxc/rootfs/host_canary

for rt in "${RUNTIMES[@]}"; do
    case "$rt" in
        docker)
            out=$(docker run --rm -v "${CANARY_DIR}:/host_canary:ro" redteam-sandbox:latest /red_team/escape_suite_v2.sh "$HOST_K")
            ;;
        podman)
            out=$(run_podman run --rm -v "${CANARY_DIR}:/host_canary:ro" docker.io/library/redteam-sandbox:latest /red_team/escape_suite_v2.sh "$HOST_K")
            ;;
        containerd)
            out=$(nerdctl run --rm -v "${CANARY_DIR}:/host_canary:ro" redteam-sandbox:latest /red_team/escape_suite_v2.sh "$HOST_K")
            ;;
        gvisor)
            out=$(docker run --rm --runtime=runsc -v "${CANARY_DIR}:/host_canary:ro" redteam-sandbox:latest /red_team/escape_suite_v2.sh "$HOST_K")
            ;;
        lxc)
            lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
            lxc-start -n redteam-lxc -s "lxc.mount.entry=${CANARY_DIR} host_canary none ro,bind 0 0" >/dev/null 2>&1
            sleep 1.5
            out=$(lxc-attach -n redteam-lxc -- /red_team/escape_suite_v2.sh "$HOST_K")
            lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
            ;;
    esac
    while IFS= read -r line; do
        [ -n "$line" ] && echo "${rt},${line}" >> results/module2_escapes.csv
    done <<< "$out"
    echo "  escapes | ${rt}: $(echo "$out" | grep '^SUMMARY') | $(echo "$out" | grep '^P10_') | $(echo "$out" | grep '^P15_')"
done

rm -rf "$CANARY_DIR"

# ----------------------------------------------------------------
# PART B: Capped Fork-Bomb (Unconstrained vs. pids.max=64)
# ----------------------------------------------------------------
echo "[Part B] Running fork_bomb (target=500): unconstrained vs. capped (64 PIDs)..."

for mode in "unconstrained" "capped_64pids"; do
    for rt in "${RUNTIMES[@]}"; do
        for t in $(seq 1 "$TRIALS"); do
            raw_out=""
            rc=0
            if [ "$mode" = "unconstrained" ]; then
                case "$rt" in
                    docker)     raw_out=$(docker run --rm redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    podman)     raw_out=$(run_podman run --rm docker.io/library/redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    containerd) raw_out=$(nerdctl run --rm redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    gvisor)     raw_out=$(docker run --rm --runtime=runsc redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    lxc)
                        lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                        lxc-start -n redteam-lxc >/dev/null 2>&1
                        sleep 1.5
                        raw_out=$(lxc-attach -n redteam-lxc -- /red_team/fork_bomb 500 2>/dev/null); rc=$?
                        lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                        ;;
                esac
            else
                case "$rt" in
                    docker)     raw_out=$(docker run --rm --pids-limit=64 redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    podman)     raw_out=$(run_podman run --rm --pids-limit=64 docker.io/library/redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    containerd) raw_out=$(nerdctl run --rm --pids-limit=64 redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    gvisor)     raw_out=$(docker run --rm --runtime=runsc --pids-limit=64 redteam-sandbox:latest /red_team/fork_bomb 500 2>/dev/null); rc=$? ;;
                    lxc)
                        lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                        lxc-start -n redteam-lxc >/dev/null 2>&1
                        sleep 1.5
                        lxc-cgroup -n redteam-lxc pids.max 64 >/dev/null 2>&1 || true
                        raw_out=$(lxc-attach -n redteam-lxc -- /red_team/fork_bomb 500 2>/dev/null); rc=$?
                        lxc-stop -k -n redteam-lxc >/dev/null 2>&1 || true
                        ;;
                esac
            fi

            res=$(echo "$raw_out" | grep '^FORK_RESULT' | head -n 1)
            if [ -n "$res" ]; then
                IFS=, read -r _ tgt spw err <<< "$res"
                if [ "$spw" -eq "$tgt" ] && [ "$err" -eq 0 ]; then
                    outcome="UNCONSTRAINED_FULL"
                elif [ "$err" -eq 11 ]; then
                    outcome="CAPPED_EAGAIN"
                else
                    outcome="PARTIAL_ERR_${err}"
                fi
                echo "${rt},${mode},${t},${tgt},${spw},${err},${rc},${outcome}" >> results/module2_forkbomb.csv
                echo "  fork    | ${rt} (${mode}) T${t} -> spawned=${spw}/${tgt}, errno=${err}, exit=${rc}, ${outcome}"
            else
                outcome="SANDBOX_EXIT_${rc}"
                echo "${rt},${mode},${t},500,,,${rc},${outcome}" >> results/module2_forkbomb.csv
                echo "  fork    | ${rt} (${mode}) T${t} -> no_guest_output, exit=${rc}, ${outcome}"
            fi
        done
    done
done

# ----------------------------------------------------------------
# PART C: 8-Thread CPU Starvation vs. 4-Worker CPU-Only Host Workload
# ----------------------------------------------------------------
echo "[Part C] Measuring fresh 4-worker CPU-only host baseline (2s warmup + 6s)..."
python3 blue_team/host_workload.py --cpu-only --workers 4 --warmup 2 --duration 6 --out results/module2_host_baseline.json
BASE_OPS=$(python3 -c "import json; print(json.load(open('results/module2_host_baseline.json'))['throughput_ops_sec'])")
BASE_MS=$(python3 -c "import json; print(json.load(open('results/module2_host_baseline.json'))['mean_ms'])")
echo "  host baseline (4 workers): ${BASE_OPS} ops/sec (mean loop ${BASE_MS} ms)"

for mode in "unconstrained" "capped_1cpu"; do
    for rt in "${RUNTIMES[@]}"; do
        for t in $(seq 1 "$TRIALS"); do
            cname="stress-ctr"
            [ "$rt" = "lxc" ] && cname="redteam-lxc"
            cleanup_ctr "$rt" "$cname"

            if [ "$mode" = "unconstrained" ]; then
                case "$rt" in
                    docker)     docker run -d --name "$cname" redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    podman)     run_podman run -d --name "$cname" docker.io/library/redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    containerd) nerdctl run -d --name "$cname" redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    gvisor)     docker run -d --runtime=runsc --name "$cname" redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    lxc)
                        lxc-start -n redteam-lxc >/dev/null 2>&1
                        sleep 1.5
                        lxc-attach -n redteam-lxc -- /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 &
                        ;;
                esac
            else
                case "$rt" in
                    docker)     docker run -d --cpus=1 --name "$cname" redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    podman)     run_podman run -d --cpus=1 --name "$cname" docker.io/library/redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    containerd) nerdctl run -d --cpus=1 --name "$cname" redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    gvisor)     docker run -d --runtime=runsc --cpus=1 --name "$cname" redteam-sandbox:latest /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 ;;
                    lxc)
                        lxc-start -n redteam-lxc >/dev/null 2>&1
                        sleep 1.5
                        lxc-cgroup -n redteam-lxc cpu.max "100000 100000" >/dev/null 2>&1 || true
                        lxc-attach -n redteam-lxc -- /red_team/stress_virus --threads 8 --sec 10 >/dev/null 2>&1 &
                        ;;
                esac
            fi

            sleep 1.5
            rm -f /tmp/m2_host.json
            python3 blue_team/host_workload.py --cpu-only --workers 4 --duration 6 --out /tmp/m2_host.json
            cleanup_ctr "$rt" "$cname"
            sleep 1.0

            row=$(python3 - "$rt" "$mode" "$t" "$BASE_OPS" << 'PYEOF'
import json, sys
rt, mode, trial, base_ops = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
hw = json.load(open("/tmp/m2_host.json"))
util = min(100.0, round((hw["throughput_ops_sec"] / base_ops) * 100.0, 2)) if base_ops > 0 else 0.0
print(f"{rt},{mode},{trial},{hw['mean_ms']},{hw['throughput_ops_sec']},{util}")
PYEOF
)
            echo "$row" >> results/module2_starvation.csv
            echo "  stress  | ${rt} (${mode}) T${t} -> ${row}"
        done
    done
done

chown -R "${REAL_USER}:${REAL_USER}" results/
echo "================================================================"
echo " MODULE 2 COMPLETE! Saved module2_escapes, forkbomb & starvation CSVs"
echo "================================================================"
