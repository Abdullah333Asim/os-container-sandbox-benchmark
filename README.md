# Evaluating Security Isolation, Performance Overhead, and Monitoring Visibility Across Five Linux Container Runtimes

This project compares five Linux container tools—**Docker**, **Podman (rootless)**, **containerd**, **gVisor**, and **LXC**—on the same Ubuntu machine. We test how well each runtime blocks unsafe operations, how much overhead it adds to system calls, disk I/O, memory, and networking, and how clearly host security monitors can detect attacks running inside a container.

## Team Members
- **Muhammad Abdullah Asim**
- **Maaz Ahmed Siddiqui**
- **Bilal Sheraz**

---

## What We Tested

1. **Module 1 - Baseline Overhead, Basic Security & Polling Monitor:** Measured startup time, idle RAM, small-block disk writes, 8 basic security checks, and 135 simulated attack trials monitored by a timer-based host polling script (`psutil`).
2. **Module 2 - System Calls & Network Speed:** Measured exact latency for 5 Linux system call operations (`getpid`, `open/close`, `pipe`, `mmap`, `fork`) against the bare host, plus container-to-host TCP speed and raw socket (`SOCK_RAW`) blocking.
3. **Module 3 - Active Security Audit, Fork Bomb & CPU Starvation:** Expanded to 15 active security checks (including reading a shared host `root` secret file), a 500-process fork bomb, and an 8-thread CPU stress test—comparing default settings against cgroup v2 limits (`64` PIDs and `1` CPU).
4. **Module 4 - Kernel eBPF Monitor & Final Comparison:** Re-ran all 135 simulated attack trials using an event-driven Linux kernel monitor (`bpftrace`) to compare against polling, then combined all results into a weighted comparison across three example use cases.

---

## Project Folders

```text
os-container-sandbox-benchmark/
├── setup/          # Installs all 5 runtimes and builds the shared test image
├── red_team/       # C attack test programs, fork bomb, CPU stress, and security check scripts
├── microbench/     # C benchmarks for system call latency and TCP networking
├── blue_team/      # Host workload, polling monitor, and kernel eBPF monitor
├── benchmarks/     # Scripts that run Modules 1, 2, and 3
├── analysis/       # Python scripts that build summary tables and Figures 1-11
├── results/        # All raw CSV data, summary tables, and saved PNG graphs
└── report/         # IEEE LaTeX report (main.tex) and ready-to-upload overleaf_bundle.zip
```

---

## Requirements

- Ubuntu 24.04 or 26.04 (64-bit, cgroups v2). A VMware VM (4 vCPUs, 16 GB RAM, 40 GB disk) is recommended.

---

## How to Run the Project

### 1. Download the Repository

```bash
git clone [https://github.com/Abdullah333Asim/os-container-sandbox-benchmark.git](https://github.com/Abdullah333Asim/os-container-sandbox-benchmark.git)
cd os-container-sandbox-benchmark
```

### 2. Install All 5 Runtimes and `bpftrace`

```bash
chmod +x setup/install_runtimes.sh
./setup/install_runtimes.sh
sudo apt-get install -y bpftrace
sudo systemctl reboot -i
```

*(Reboot once so Docker permissions and rootless Podman user settings take effect.)*

### 3. Create the LXC Container and Build All Test Programs

This builds one Ubuntu 24.04 container image and copies the exact same compiled C programs into all 5 runtimes and onto the host:

```bash
sudo lxc-create -t download -n redteam-lxc -- -d ubuntu -r noble -a amd64
chmod +x setup/build_images.sh
./setup/build_images.sh
```

### 4. Run the Four Modules

Pass `1` instead of `3` or `5` for a quick test run *(script names match the internal repo files)*:

```bash
# Module 1: Baseline overhead + 135 polling monitor trials (~8 min)
sudo ./benchmarks/run_all.sh 3

# Module 2: System call and TCP network benchmarks, 5 trials (~2 min)
sudo ./benchmarks/run_module1.sh 5

# Module 3: 15 security checks, fork bomb, and CPU stress, 3 trials (~5 min)
sudo ./benchmarks/run_module2.sh 3

# Module 4: 135 kernel eBPF monitor trials (~3 min)
sudo python3 blue_team/ebpf_arena.py --trials 3 --timeout 4.0 --out results/module3_ebpf_arena.csv
```

### 5. Generate All Tables and Figures

```bash
python3 analysis/plot_results.py
python3 analysis/plot_module1.py
python3 analysis/plot_module2.py
python3 analysis/plot_module3.py
```

All graphs (`fig1` through `fig11`) are saved in `results/figures/`.

---

## Summary of Results

| Runtime | 15-Check Security | Capabilities | Startup (ms) | Idle RAM (MB) | Disk I/O (MB/s) | TCP Speed (MB/s) | Polling Catch Rate | eBPF Catch Rate | eBPF Kill Time (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Docker** | 8/15 (53.3%) | 14 | 532.7 | **1.5** | 92.0 | **1,968.7** | 100.0% | 100.0% | 548.6 |
| **Podman (rootless)** | **11/15 (73.3%)** | **11** | 460.0 | 1.6 | **134.3** | 641.7 | 100.0% | 100.0% | **544.6** |
| **containerd** | 8/15 (53.3%) | 14 | 924.0 | 1.6 | 107.3 | 1,796.0 | 100.0% | 100.0% | 956.6 |
| **gVisor** | 10/15 (66.7%) | 13 | 456.3 | 46.5 | 24.0 | 573.4 | 66.7% | 0.0% | N/A |
| **LXC** | 2/15 (13.3%) | 36 | **379.0** | 78.8 | 113.8 | 1,840.5 | 100.0% | 100.0% | 776.6 |

### Main Takeaways

- **Best for security + everyday use — Rootless Podman:** Earned the highest security score, was the only runtime that blocked reading a shared host `root` file, matched native system call and disk speed, and kept full visibility for both monitors—with the trade-off of slower container-to-host TCP networking.
- **Best for high-speed networking — Docker & containerd:** Delivered the fastest TCP speeds, near-native system calls, and full eBPF visibility, though operators should still drop unused capabilities (such as `CAP_NET_RAW`) and set cgroup limits.
- **Best for separating untrusted code from the host kernel — gVisor:** Strong kernel isolation via its user-space Sentry kernel, but much slower on system calls (3.25x–30.68x) and small disk writes, and it completely hides container activity from host eBPF monitors.
- **Cgroup limits are required everywhere:** Under default settings, all 5 runtimes allowed a full 500-process fork bomb and let an 8-thread CPU attack drop host throughput to roughly 55%–58%. Enforcing cgroup v2 limits contained both attacks across every runtime.
- **Avoid default rootful LXC for untrusted code:** Left the widest attack surface open (36 capabilities, including `mount` and `bpf`).

---

## Report

The full IEEE paper is in `report/main.tex`. To view or compile it directly in Overleaf without manual setup, upload `report/overleaf_bundle.zip` (which already includes `main.tex` and all 11 figures).
