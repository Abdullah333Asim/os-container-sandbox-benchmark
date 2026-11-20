#!/usr/bin/env python3
import argparse
import json
import os
import pwd
import subprocess
import time
import psutil

def podman_cmd(podman_user, subargs):
    pw = pwd.getpwnam(podman_user)
    return [
        "sudo", "-u", podman_user, "env",
        f"XDG_RUNTIME_DIR=/run/user/{pw.pw_uid}",
        f"HOME={pw.pw_dir}",
        "podman",
    ] + subargs

def get_root_pid(runtime, container, podman_user):
    try:
        if runtime in ("docker", "gvisor"):
            cmd = ["docker", "inspect", "-f", "{{.State.Pid}}", container]
        elif runtime == "podman":
            cmd = podman_cmd(podman_user, ["inspect", "-f", "{{.State.Pid}}", container])
        elif runtime == "containerd":
            cmd = ["nerdctl", "inspect", "-f", "{{.State.Pid}}", container]
        elif runtime == "lxc":
            cmd = ["lxc-info", "-n", container, "-pH"]
        else:
            return 0
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0

def get_container_pids(runtime, root_pid):
    if root_pid <= 0:
        return set()
    pids = {root_pid}

    try:
        with open(f"/proc/{root_pid}/cgroup", "r") as f:
            line = f.readline().strip()
        cg_rel = line.split("::")[-1]
        if runtime == "lxc" and cg_rel.endswith("/init.scope"):
            cg_rel = os.path.dirname(cg_rel)
        cg_dir = f"/sys/fs/cgroup{cg_rel}"
        if any(k in cg_rel for k in ("docker", "libpod", "lxc", "default", "nerdctl", "containerd")) and os.path.isdir(cg_dir):
            for dirpath, _, filenames in os.walk(cg_dir):
                if "cgroup.procs" in filenames:
                    try:
                        with open(os.path.join(dirpath, "cgroup.procs"), "r") as f:
                            for p in f:
                                if p.strip().isdigit():
                                    pids.add(int(p.strip()))
                    except Exception:
                        pass
    except Exception:
        pass

    try:
        parent = psutil.Process(root_pid)
        for child in parent.children(recursive=True):
            pids.add(child.pid)
        # Include all gVisor sandbox helpers (gvisor_sentry, runsc-gofer, etc.) under containerd-shim
        if runtime == "gvisor":
            shim = parent.parent()
            if shim and "containerd-shim" in shim.name():
                for sib in shim.children(recursive=True):
                    pids.add(sib.pid)
    except Exception:
        pass

    return pids

def read_io_written_bytes(pid):
    try:
        with open(f"/proc/{pid}/io", "r") as f:
            for line in f:
                if line.startswith("wchar:"):
                    return int(line.split()[1])
    except Exception:
        return 0
    return 0

def kill_container(runtime, container, podman_user):
    if runtime in ("docker", "gvisor"):
        cmd = ["docker", "kill", container]
    elif runtime == "podman":
        cmd = podman_cmd(podman_user, ["kill", container])
    elif runtime == "containerd":
        cmd = ["nerdctl", "kill", container]
    elif runtime == "lxc":
        cmd = ["lxc-stop", "-k", "-n", container]
    else:
        return
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True, choices=["docker", "podman", "containerd", "gvisor", "lxc"])
    parser.add_argument("--container", required=True)
    parser.add_argument("--podman-user", default=os.environ.get("SUDO_USER", os.environ.get("USER", "root")))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--cpu-thresh", type=float, default=30.0)
    parser.add_argument("--mem-thresh-mb", type=float, default=180.0)
    parser.add_argument("--io-thresh-mb", type=float, default=5.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    t_start = time.perf_counter()
    prev_cpu_time = {}
    lxc_init_io_base = None
    prev_t = t_start

    peak_cpu = 0.0
    peak_mem_mb = 0.0
    peak_io_mb = 0.0
    cpu_hits = 0
    inner_proc_visible = False
    visible_names = set()

    detected = False
    trigger = "timeout"
    mttd_ms = args.timeout * 1000.0
    containment_ms = 0.0

    while (time.perf_counter() - t_start) < args.timeout:
        time.sleep(0.2)
        now = time.perf_counter()
        dt = max(now - prev_t, 0.01)

        root_pid = get_root_pid(args.runtime, args.container, args.podman_user)
        pids = get_container_pids(args.runtime, root_pid)
        if not pids:
            prev_t = now
            continue

        total_cpu_pct = 0.0
        total_rss_mb = 0.0
        total_io_bytes = 0

        for pid in list(pids):
            try:
                p = psutil.Process(pid)
                pname = p.name()
                cmdline_str = " ".join(p.cmdline())
                if "/red_team/" in cmdline_str:
                    inner_proc_visible = True
                    visible_names.add(pname)

                ct = p.cpu_times()
                c_total = ct.user + ct.system
                if pid in prev_cpu_time:
                    delta_c = max(0.0, c_total - prev_cpu_time[pid])
                    total_cpu_pct += (delta_c / dt) * 100.0
                prev_cpu_time[pid] = c_total

                total_rss_mb += p.memory_info().rss / (1024 * 1024)

                wbytes = read_io_written_bytes(pid)
                if args.runtime == "lxc" and pid == root_pid:
                    if lxc_init_io_base is None:
                        lxc_init_io_base = wbytes
                    total_io_bytes += max(0, wbytes - lxc_init_io_base)
                else:
                    total_io_bytes += wbytes
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        io_mb = total_io_bytes / (1024 * 1024)
        peak_cpu = max(peak_cpu, total_cpu_pct)
        peak_mem_mb = max(peak_mem_mb, total_rss_mb)
        peak_io_mb = max(peak_io_mb, io_mb)
        prev_t = now

        if total_cpu_pct >= args.cpu_thresh:
            cpu_hits += 1
        else:
            cpu_hits = 0

        if cpu_hits >= 2:
            detected, trigger = True, "cpu"
        elif total_rss_mb >= args.mem_thresh_mb:
            detected, trigger = True, "memory"
        elif io_mb >= args.io_thresh_mb:
            detected, trigger = True, "io"

        if detected:
            t_detect = time.perf_counter()
            mttd_ms = (t_detect - t_start) * 1000.0
            kill_container(args.runtime, args.container, args.podman_user)
            for _ in range(50):
                if get_root_pid(args.runtime, args.container, args.podman_user) == 0:
                    break
                time.sleep(0.05)
            containment_ms = (time.perf_counter() - t_detect) * 1000.0
            break

    if not detected:
        kill_container(args.runtime, args.container, args.podman_user)

    result = {
        "runtime": args.runtime,
        "detected": detected,
        "trigger": trigger,
        "mttd_ms": round(mttd_ms, 2),
        "containment_ms": round(containment_ms, 2),
        "total_response_ms": round(mttd_ms + containment_ms, 2),
        "peak_cpu_pct": round(peak_cpu, 2),
        "peak_mem_mb": round(peak_mem_mb, 2),
        "peak_io_mb": round(peak_io_mb, 2),
        "inner_proc_visible": inner_proc_visible,
        "visible_names": sorted(list(visible_names)),
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result))

if __name__ == "__main__":
    main()
