#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
plt.rcParams["axes.ymargin"] = 0.16

os.makedirs("results/figures", exist_ok=True)

ORDER = ["docker", "podman", "containerd", "gvisor", "lxc"]
LABELS = {
    "docker": "Docker\n(runc)",
    "podman": "Podman\n(rootless)",
    "containerd": "containerd\n(nerdctl)",
    "gvisor": "gVisor\n(runsc)",
    "lxc": "LXC\n(system)"
}
COLORS = ["#2b5c8f", "#2e8b57", "#4f81bd", "#c0392b", "#7f8c8d"]

plt.rcParams.update({
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "figure.dpi": 300,
})

startup = pd.read_csv("results/startup_overhead.csv")
io_df = pd.read_csv("results/io_overhead.csv")
probes = pd.read_csv("results/security_probes.csv")
arena = pd.read_csv("results/arena_results.csv")

# Parse security scores & capability counts
probe_rows = probes[probes["probe"] != "SUMMARY"].copy()
sec_scores = {}
cap_counts = {}
for rt in ORDER:
    sub = probe_rows[probe_rows["runtime"] == rt]
    blocked = (sub["status"] == "BLOCKED").sum()
    sec_scores[rt] = round((blocked / 8.0) * 100.0, 1)
    summ = probes[(probes["runtime"] == rt) & (probes["probe"] == "SUMMARY")]
    cap_str = summ["detail"].values[0] if len(summ) else "CAP_COUNT=0"
    cap_counts[rt] = int(cap_str.split("=")[-1])

# ----------------------------------------------------------------
# FIG 1: Isolation Score vs. Cold-Start Latency (Dual-Axis)
# ----------------------------------------------------------------
st_mean = startup.groupby("runtime")["startup_ms"].mean().reindex(ORDER)
sec_vals = [sec_scores[rt] for rt in ORDER]

fig, ax1 = plt.subplots(figsize=(7.5, 4.2))
x = np.arange(len(ORDER))
bars = ax1.bar(x, sec_vals, width=0.52, color="#d0d7de", edgecolor="#24292f", linewidth=1.0, label="Security Isolation Score (%)")
ax1.set_ylabel("Security Isolation Score (%)", color="#24292f")
ax1.set_ylim(0, 128)
ax1.set_xticks(x)
ax1.set_xticklabels([LABELS[rt] for rt in ORDER])

for bar, val in zip(bars, sec_vals):
    ax1.text(bar.get_x() + bar.get_width()/2, val + 2.5, f"{val:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

ax2 = ax1.twinx()
ax2.plot(x, st_mean.values, color="#c0392b", marker="o", linewidth=2.2, markersize=7, label="Cold-Start Latency (ms)")
ax2.set_ylabel("Cold-Start Latency (ms)", color="#c0392b")
ax2.tick_params(axis="y", labelcolor="#c0392b")
ax2.set_ylim(0, max(st_mean.values) * 1.28)

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", frameon=True)
plt.title("Security Isolation Score vs. Container Cold-Start Latency")
fig.tight_layout()
plt.savefig("results/figures/fig1_isolation_vs_startup.png", dpi=300)
plt.close()

# ----------------------------------------------------------------
# FIG 2: Idle RAM Footprint & Disk I/O Throughput Overhead
# ----------------------------------------------------------------
ram_mean = startup.groupby("runtime")["idle_ram_mb"].mean().reindex(ORDER)
io_mean = io_df.groupby("runtime")["throughput_mb_s"].mean().reindex(ORDER)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.5, 4.0))
ax1.bar(x, ram_mean.values, color=COLORS, edgecolor="black", linewidth=0.8)
ax1.set_title("(a) Idle Container RAM Footprint")
ax1.set_ylabel("Resident Memory (MB)")
ax1.set_xticks(x)
ax1.set_xticklabels([LABELS[rt] for rt in ORDER], fontsize=8.5)
for i, v in enumerate(ram_mean.values):
    ax1.text(i, v + max(ram_mean.values)*0.02, f"{v:.1f}", ha="center", va="bottom", fontsize=8.5)

ax2.bar(x, io_mean.values, color=COLORS, edgecolor="black", linewidth=0.8)
ax2.set_title("(b) 16 MB Syscall-Heavy Write (32k x 512B)")
ax2.set_ylabel("Throughput (MB/s) — Higher is Better")
ax2.set_xticks(x)
ax2.set_xticklabels([LABELS[rt] for rt in ORDER], fontsize=8.5)
for i, v in enumerate(io_mean.values):
    ax2.text(i, v + max(io_mean.values)*0.02, f"{v:.1f}", ha="center", va="bottom", fontsize=8.5)

fig.suptitle("Runtime Resource Footprint & Filesystem I/O Overhead", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig2_resource_io_overhead.png", dpi=300, bbox_inches="tight")
plt.close()

# ----------------------------------------------------------------
# FIG 3: Security Probe Matrix Heatmap (8 Probes x 5 Runtimes)
# ----------------------------------------------------------------
probe_order = [
    "P1_KERNEL_MASK", "P2_PROC_MODULES", "P3_DMESG_LOG", "P4_USERNS_ISOLATION",
    "P5_CAP_NET_RAW", "P6_SYSCALL_MOUNT", "P7_SYSCALL_UNSHARE", "P8_SYSCALL_MKNOD"
]
probe_pretty = [
    "Kernel Mask", "/proc/modules", "Host dmesg", "User-NS UID Map",
    "Drop CAP_NET_RAW", "Block mount()", "Block unshare()", "Block mknod()"
]

mat = np.zeros((len(probe_order), len(ORDER)))
for i, pr in enumerate(probe_order):
    for j, rt in enumerate(ORDER):
        row = probe_rows[(probe_rows["runtime"] == rt) & (probe_rows["probe"] == pr)]
        mat[i, j] = 1.0 if (len(row) and row["status"].values[0] == "BLOCKED") else 0.0

fig, ax = plt.subplots(figsize=(7.8, 4.8))
ax.imshow(mat, cmap=plt.cm.RdYlGn, vmin=-0.15, vmax=1.15, aspect="auto")
ax.set_xticks(np.arange(len(ORDER)))
ax.set_xticklabels([f"{LABELS[rt]}\n(Caps: {cap_counts[rt]})" for rt in ORDER], fontsize=8.5)
ax.set_yticks(np.arange(len(probe_order)))
ax.set_yticklabels(probe_pretty, fontsize=9)

for i in range(len(probe_order)):
    for j in range(len(ORDER)):
        txt = "BLOCKED" if mat[i, j] == 1.0 else "EXPOSED"
        ax.text(j, i, txt, ha="center", va="center", color="black", fontsize=8.5, fontweight="bold")

plt.title("Out-of-the-Box Security Isolation Probe Matrix")
fig.tight_layout()
plt.savefig("results/figures/fig3_security_probe_heatmap.png", dpi=300)
plt.close()

# ----------------------------------------------------------------
# FIG 4: Polling Monitor Response Time & Benign Host Utility Under Attack
# ----------------------------------------------------------------
det_df = arena[arena["detected"] == True]
resp_by_virus = det_df.pivot_table(index="runtime", columns="virus", values="total_response_ms", aggfunc="mean").reindex(ORDER)
util_mean = arena.groupby("runtime")["host_utility_pct"].mean().reindex(ORDER)
det_rate = (arena.groupby("runtime")["detected"].mean() * 100.0).reindex(ORDER)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.8, 4.2))
w = 0.25
vcols = ["cpu_virus", "mem_virus", "io_virus"]
vcolors = ["#2b5c8f", "#e67e22", "#27ae60"]
for idx, vc in enumerate(vcols):
    vals = resp_by_virus[vc].fillna(0).values if vc in resp_by_virus.columns else np.zeros(len(ORDER))
    ax1.bar(x + (idx - 1)*w, vals, width=w, label=vc, color=vcolors[idx], edgecolor="black", linewidth=0.6)
ax1.set_title("(a) Polling Monitor Response Time (Detected Trials)")
ax1.set_ylabel("MTTD + Containment Time (ms)")
ax1.set_xticks(x)
ax1.set_xticklabels([LABELS[rt] for rt in ORDER], fontsize=8.5)
ax1.legend(fontsize=8.5)

w2 = 0.35
ax2.bar(x - w2/2, det_rate.values, width=w2, label="Detection Rate (%)", color="#2b5c8f", edgecolor="black", linewidth=0.6)
ax2.bar(x + w2/2, util_mean.values, width=w2, label="Benign Host Utility (%)", color="#2e8b57", edgecolor="black", linewidth=0.6)
ax2.set_title("(b) Detection Efficacy & Host Utility")
ax2.set_ylabel("Percentage (%)")
ax2.set_ylim(0, 118)
ax2.set_xticks(x)
ax2.set_xticklabels([LABELS[rt] for rt in ORDER], fontsize=8.5)
ax2.legend(fontsize=8.5, loc="lower right")

fig.suptitle("Polling Monitor Containment Time, Detection Rate & Host Utility", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig4_blueteam_and_host_utility.png", dpi=300, bbox_inches="tight")
plt.close()

# ----------------------------------------------------------------
# Print Summary Table for Report
# ----------------------------------------------------------------
summary = pd.DataFrame({
    "Security_Score_%": [sec_scores[rt] for rt in ORDER],
    "Default_Caps": [cap_counts[rt] for rt in ORDER],
    "Startup_ms": st_mean.round(1).values,
    "Idle_RAM_MB": ram_mean.round(1).values,
    "Disk_IO_MB_s": io_mean.round(1).values,
    "Detection_Rate_%": det_rate.round(1).values,
    "Mean_Response_ms": det_df.groupby("runtime")["total_response_ms"].mean().reindex(ORDER).round(1).values,
    "Host_Utility_%": util_mean.round(1).values,
    "Inner_Proc_Visible": arena.groupby("runtime")["inner_proc_visible"].any().reindex(ORDER).values,
}, index=ORDER)

summary.to_csv("results/summary_table.csv")
print("\n=== BENCHMARK SUMMARY TABLE ===")
print(summary.to_string())
print("\nSaved 4 figures to results/figures/ and results/summary_table.csv")
