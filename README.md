# Evaluating Security Isolation vs. Performance Overhead Across Five Linux Container Runtimes

An empirical Operating Systems and Cyber Defense benchmark comparing **Docker (`runc`)**, **Podman (rootless)**, **containerd (`nerdctl`)**, **gVisor (`runsc`)**, and **LXC** across out-of-the-box attack surface, resource/syscall overhead, host blast-radius containment, and host-side Blue Team observability under multi-generational Red Team workloads.

## Team Members
- **Muhammad Abdullah Asim**: Runtime infrastructure, 5-container provisioning, image parity, startup/I/O benchmarking
- **Maaz**: Red Team multi-generational C malware payloads, container security probe suite, orchestration testing
- **Bilal**: Blue Team host-side monitor/containment daemon, host ground-truth workload, automated analysis & plotting, final report

---

## Repository Structure

```text
os-container-sandbox-benchmark/
├── setup/
│   └── install_runtimes.sh       # Automated installer for all 5 container runtimes & Python dependencies
├── red_team/
│   ├── Dockerfile                # Builds the identical Ubuntu 24.04 Red Team image used across runtimes
│   ├── cpu_virus.c               # Gen 1-3 CPU exhaustion, pulsed timing, and process-camouflage payload
│   ├── mem_virus.c               # Gen 1-3 physical RAM allocation (400 MB) and slow-drip evasion payload
│   ├── io_virus.c                # Gen 1-3 persistence drop + noisy disk write payload
│   ├── run_virus.sh              # Container PID-1 wrapper keeping Gen 3 orphaned children alive
│   └── security_probes.sh        # 8-point safe OS isolation & capability audit suite
├── blue_team/
│   ├── host_workload.py          # Benign host CPU + fsync ground-truth workload (measures host utility %)
│   └── blue_team_monitor.py      # Host-side cgroup/proc telemetry monitor & automated container killer
├── benchmarks/
│   └── run_all.sh                # Master 5-phase benchmark orchestrator (5 runtimes x 3 viruses x 3 gens x N trials)
├── analysis/
│   └── plot_results.py           # Generates 300-DPI IEEE figures and summary_table.csv from raw CSVs
└── results/
    ├── startup_overhead.csv      # Phase 1: Cold-start latency (ms) and idle RAM footprint (MB)
    ├── io_overhead.csv           # Phase 2: Inside-container syscall-heavy disk write throughput (MB/s)
    ├── security_probes.csv       # Phase 3: 8-probe security matrix and default capability counts
    ├── host_baseline.json        # Phase 4: Idle host ground-truth baseline throughput
    ├── arena_results.csv         # Phase 5: 135-trial Red Team vs. Blue Team telemetry dataset
    ├── summary_table.csv         # Aggregated comparison table across all 5 runtimes
    └── figures/                  # Publication-ready PNG figures (Fig. 1 - Fig. 4)
```

---

## Prerequisites & Testbed Environment

- **OS:** Ubuntu 24.04 / 26.04 (64-bit, cgroups v2, native `systemd`; VMware VM recommended over WSL2)
- **Recommended VM Specs:** 16 GB RAM, 4 vCPUs, 40 GB Disk, NAT networking

---

## Step-by-Step Reproduction Guide

### 1. Clone the Repository

```bash
git clone https://github.com/Abdullah333Asim/os-container-sandbox-benchmark.git
cd os-container-sandbox-benchmark
```

### 2. Install All 5 Runtimes & Dependencies

```bash
chmod +x setup/install_runtimes.sh
./setup/install_runtimes.sh
sudo systemctl reboot -i
```

*(A single reboot ensures your user's `docker` group and rootless `podman` UID/GID mappings initialize cleanly.)*

### 3. Build & Load the Identical Red Team Test Image Across All 5 Runtimes

```bash
# Build in Docker (automatically available to Docker and gVisor)
docker build -t redteam-sandbox:latest red_team/

# Export and load identical image into Podman and containerd (nerdctl)
docker save redteam-sandbox:latest -o /tmp/redteam-sandbox.tar
podman load -i /tmp/redteam-sandbox.tar
sudo nerdctl load -i /tmp/redteam-sandbox.tar
rm -f /tmp/redteam-sandbox.tar

# Create persistent LXC container and copy compiled /red_team binaries into it
sudo lxc-create -t download -n redteam-lxc -- -d ubuntu -r noble -a amd64
docker create --name tmp_extract redteam-sandbox:latest >/dev/null
docker cp tmp_extract:/red_team /tmp/red_team_extract
docker rm tmp_extract >/dev/null
sudo cp -r /tmp/red_team_extract /var/lib/lxc/redteam-lxc/rootfs/red_team
rm -rf /tmp/red_team_extract
```

### 4. Run the Full 5-Phase Benchmark Suite

Run with `1` for a quick ~3-minute verification, or `3` for the full 135-trial dataset (~8 minutes):

```bash
sudo ./benchmarks/run_all.sh 3
```

### 5. Generate Summary Table & Figures

```bash
python3 analysis/plot_results.py
```

Outputs are saved to `results/summary_table.csv` and `results/figures/fig1_*.png` through `fig4_*.png`.

---

## Summary of Key Empirical Findings (3-Trial Dataset)

| Runtime | Security Score | Default Caps | Startup (ms) | Idle RAM (MB) | Syscall I/O (MB/s) | Detection Rate | Mean Response (ms) | Host Utility | Inner PIDs Visible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Docker (`runc`)** | 50.0% (4/8) | 14 | 532.7 | 1.5 | 92.0 | 100.0% | 2029.3 | 97.0% | Yes |
| **Podman (rootless)** | **87.5% (7/8)** | **11** | 460.0 | 1.6 | **134.3** | 100.0% | 2136.8 | **99.9%** | Yes |
| **containerd (`nerdctl`)** | 50.0% (4/8) | 14 | 924.0 | 1.6 | 107.3 | 100.0% | **1965.4** | 99.0% | Yes |
| **gVisor (`runsc`)** | **87.5% (7/8)** | 13 | 456.3 | 46.5 | 24.0 | 66.7% | 5399.6 | 97.8% | **No** |
| **LXC (system)** | 12.5% (1/8) | 36 | **379.0** | 78.8 | 113.8 | 100.0% | 2412.9 | 99.3% | Yes |
