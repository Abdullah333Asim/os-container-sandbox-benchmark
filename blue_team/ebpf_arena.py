#!/usr/bin/env python3
import argparse
import csv
import os
import pwd
import queue
import subprocess
import sys
import threading
import time

RUNTIMES = ["docker", "podman", "containerd", "gvisor", "lxc"]
VIRUSES = ["cpu_virus", "mem_virus", "io_virus"]
GENS = [1, 2, 3]
CTR_NAME = "ebpf-arena-ctr"


def get_real_user_env():
    real_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    pw = pwd.getpwnam(real_user)
    return real_user, pw.pw_uid, pw.pw_dir


REAL_USER, REAL_UID, REAL_HOME = get_real_user_env()


def run_cmd(cmd, quiet=True):
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
        text=True,
    )


def podman_cmd(args):
    return [
        "sudo", "-u", REAL_USER, "env",
        f"XDG_RUNTIME_DIR=/run/user/{REAL_UID}",
        f"HOME={REAL_HOME}",
        "podman",
    ] + args


def cleanup_container(rt):
    if rt in ("docker", "gvisor"):
        run_cmd(["docker", "rm", "-f", CTR_NAME])
    elif rt == "podman":
        run_cmd(podman_cmd(["rm", "-f", "-t", "0", CTR_NAME]))
    elif rt == "containerd":
        run_cmd(["nerdctl", "rm", "-f", CTR_NAME])
    elif rt == "lxc":
        run_cmd(["lxc-stop", "-k", "-n", "redteam-lxc"])


def launch_container(rt, virus, gen):
    if rt == "docker":
        run_cmd(["docker", "run", "-d", "--name", CTR_NAME,
                 "redteam-sandbox:latest", "/red_team/run_virus.sh", virus, str(gen)])
    elif rt == "podman":
        run_cmd(podman_cmd(["run", "-d", "--name", CTR_NAME,
                            "docker.io/library/redteam-sandbox:latest",
                            "/red_team/run_virus.sh", virus, str(gen)]))
    elif rt == "containerd":
        run_cmd(["nerdctl", "run", "-d", "--name", CTR_NAME,
                 "redteam-sandbox:latest", "/red_team/run_virus.sh", virus, str(gen)])
    elif rt == "gvisor":
        run_cmd(["docker", "run", "-d", "--runtime=runsc", "--name", CTR_NAME,
                 "redteam-sandbox:latest", "/red_team/run_virus.sh", virus, str(gen)])
    elif rt == "lxc":
        subprocess.Popen(
            ["lxc-attach", "-n", "redteam-lxc", "--",
             "/red_team/run_virus.sh", virus, str(gen)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def reader_thread(proc, ev_queue):
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        ev_queue.put((time.perf_counter(), line))


def drain_queue(ev_queue):
    while True:
        try:
            ev_queue.get_nowait()
        except queue.Empty:
            break


def main():
    if os.geteuid() != 0:
        print("Run with sudo: sudo python3 blue_team/ebpf_arena.py")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--out", default="results/module3_ebpf_arena.csv")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    print("Starting persistent bpftrace kernel sensor...")
    bf_proc = subprocess.Popen(
        ["bpftrace", "-B", "line", "blue_team/ebpf_sensors.bt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    ev_q = queue.Queue()
    t_reader = threading.Thread(target=reader_thread, args=(bf_proc, ev_q), daemon=True)
    t_reader.start()

    ready = False
    t_wait = time.perf_counter()
    while time.perf_counter() - t_wait < 15.0:
        try:
            _, line = ev_q.get(timeout=0.2)
            if line == "READY":
                ready = True
                break
        except queue.Empty:
            pass

    if not ready:
        bf_proc.terminate()
        print("ERROR: bpftrace did not reach READY state.")
        sys.exit(1)

    print("bpftrace sensor READY.")

    viruses = ["io_virus"] if args.smoke else VIRUSES
    gens = [3] if args.smoke else GENS
    trials = 1 if args.smoke else args.trials

    rows = []
    try:
        for rt in RUNTIMES:
            for virus in viruses:
                for gen in gens:
                    for trial in range(1, trials + 1):
                        cleanup_container(rt)
                        if rt == "lxc":
                            run_cmd(["lxc-start", "-n", "redteam-lxc"])
                            time.sleep(1.5)

                        time.sleep(0.15)
                        drain_queue(ev_q)

                        t_launch = time.perf_counter()
                        launch_thr = threading.Thread(
                            target=launch_container, args=(rt, virus, gen)
                        )
                        launch_thr.start()

                        wrapper_ns = None
                        first_alert_ns = None
                        t_detect = None
                        trigger = "NONE"
                        prctl_seen = False
                        openat_seen = False
                        exec_seen = False

                        deadline = t_launch + args.timeout
                        while time.perf_counter() < deadline:
                            rem = max(0.02, deadline - time.perf_counter())
                            try:
                                ev_t, line = ev_q.get(timeout=min(0.1, rem))
                            except queue.Empty:
                                continue

                            parts = line.split("|")
                            if len(parts) < 5:
                                continue
                            etype, ns_str = parts[0], parts[1]
                            try:
                                ev_ns = int(ns_str)
                            except ValueError:
                                continue

                            if etype == "WRAPPER":
                                if wrapper_ns is None:
                                    wrapper_ns = ev_ns
                            elif etype in ("EXEC", "OPENAT", "PRCTL_SPOOF"):
                                if etype == "EXEC":
                                    exec_seen = True
                                elif etype == "OPENAT":
                                    openat_seen = True
                                elif etype == "PRCTL_SPOOF":
                                    prctl_seen = True

                                if t_detect is None:
                                    t_detect = ev_t
                                    first_alert_ns = ev_ns
                                    trigger = etype
                                    break

                        # Ensure container launch call finished before teardown
                        launch_thr.join(timeout=10.0)

                        # Capture any follow-up events (e.g. PRCTL_SPOOF / OPENAT) during teardown
                        t_kill_start = time.perf_counter()
                        cleanup_container(rt)
                        t_killed = time.perf_counter()

                        while True:
                            try:
                                _, line = ev_q.get_nowait()
                                parts = line.split("|")
                                if len(parts) >= 5:
                                    if parts[0] == "PRCTL_SPOOF":
                                        prctl_seen = True
                                    elif parts[0] == "OPENAT":
                                        openat_seen = True
                                    elif parts[0] == "EXEC":
                                        exec_seen = True
                            except queue.Empty:
                                break

                        detected = t_detect is not None
                        if detected:
                            mttd_launch_ms = round((t_detect - t_launch) * 1000.0, 2)
                            if wrapper_ns is not None and first_alert_ns is not None and first_alert_ns >= wrapper_ns:
                                kernel_mttd_ms = round((first_alert_ns - wrapper_ns) / 1e6, 2)
                            else:
                                kernel_mttd_ms = ""
                            kill_ms = round((t_killed - t_kill_start) * 1000.0, 2)
                            total_resp_ms = round((t_killed - t_launch) * 1000.0, 2)
                        else:
                            mttd_launch_ms = ""
                            kernel_mttd_ms = ""
                            kill_ms = ""
                            total_resp_ms = ""

                        row = {
                            "runtime": rt,
                            "virus": virus,
                            "gen": gen,
                            "trial": trial,
                            "detected": detected,
                            "trigger": trigger,
                            "mttd_from_launch_ms": mttd_launch_ms,
                            "kernel_mttd_ms": kernel_mttd_ms,
                            "kill_ms": kill_ms,
                            "total_response_ms": total_resp_ms,
                            "exec_seen": exec_seen,
                            "prctl_spoof_seen": prctl_seen,
                            "openat_seen": openat_seen,
                        }
                        rows.append(row)
                        print(
                            f"  ebpf | {rt:10s} | {virus:9s} G{gen} T{trial} | "
                            f"det={str(detected):5s} trig={trigger:11s} "
                            f"kern_ms={str(kernel_mttd_ms):6s} launch_ms={str(mttd_launch_ms):7s} "
                            f"tot_ms={str(total_resp_ms):7s} spoof={prctl_seen}"
                        )
    finally:
        bf_proc.terminate()
        try:
            bf_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bf_proc.kill()
        for rt in RUNTIMES:
            cleanup_container(rt)

    fieldnames = [
        "runtime", "virus", "gen", "trial", "detected", "trigger",
        "mttd_from_launch_ms", "kernel_mttd_ms", "kill_ms", "total_response_ms",
        "exec_seen", "prctl_spoof_seen", "openat_seen",
    ]
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    os.chown(args.out, REAL_UID, pwd.getpwnam(REAL_USER).pw_gid)
    print(f"Saved {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
