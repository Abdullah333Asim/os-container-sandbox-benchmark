#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

os.makedirs("results/figures", exist_ok=True)

ORDER = ["host", "docker", "podman", "containerd", "gvisor", "lxc"]
LABELS = {
    "host": "Bare Host\n(control)",
    "docker": "Docker\n(runc)",
    "podman": "Podman\n(rootless)",
    "containerd": "containerd\n(nerdctl)",
    "gvisor": "gVisor\n(runsc)",
    "lxc": "LXC\n(system)"
}
COLORS = ["#34495e", "#2b5c8f", "#2e8b57", "#4f81bd", "#c0392b", "#7f8c8d"]

OPS = ["getpid", "open_close", "pipe_rw", "mmap_fault_unmap", "fork_wait"]
OP_LABELS = ["getpid()", "open()+close()", "pipe() R/W", "mmap+fault\n+munmap", "fork()+wait()"]

plt.rcParams.update({
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "figure.dpi": 300,
})

sys_df = pd.read_csv("results/syscall_bench.csv")
net_df = pd.read_csv("results/net_bench.csv")

# ----------------------------------------------------------------
# Summary Tables (Mean +/- Std)
# ----------------------------------------------------------------
sys_mean = sys_df.pivot_table(index="runtime", columns="operation", values="ns_per_op", aggfunc="mean").reindex(ORDER)[OPS]
sys_std = sys_df.pivot_table(index="runtime", columns="operation", values="ns_per_op", aggfunc="std").reindex(ORDER)[OPS].fillna(0.0)

sys_summary = pd.DataFrame(index=ORDER)
for op in OPS:
    sys_summary[f"{op}_ns_mean"] = sys_mean[op].round(1)
    sys_summary[f"{op}_ns_std"] = sys_std[op].round(1)
    sys_summary[f"{op}_vs_host_x"] = (sys_mean[op] / sys_mean.loc["host", op]).round(2)
sys_summary.to_csv("results/module1_syscall_summary.csv")

net_summary = pd.DataFrame({
    "tcp_rtt_us_mean": net_df.groupby("runtime")["tcp_rtt_us"].mean().reindex(ORDER).round(2),
    "tcp_rtt_us_std": net_df.groupby("runtime")["tcp_rtt_us"].std().reindex(ORDER).fillna(0.0).round(2),
    "tcp_mb_s_mean": net_df.groupby("runtime")["tcp_throughput_mb_s"].mean().reindex(ORDER).round(2),
    "tcp_mb_s_std": net_df.groupby("runtime")["tcp_throughput_mb_s"].std().reindex(ORDER).fillna(0.0).round(2),
    "sock_raw": net_df.groupby("runtime")["sock_raw_status"].first().reindex(ORDER),
})
net_summary.to_csv("results/module1_net_summary.csv")

# ----------------------------------------------------------------
# FIG 5: Syscall & OS Primitives Microbenchmark (Log Scale, ns/op)
# ----------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9.8, 4.6))
x = np.arange(len(OPS))
width = 0.13

for idx, rt in enumerate(ORDER):
    means = sys_mean.loc[rt].values
    stds = sys_std.loc[rt].values
    offset = (idx - (len(ORDER) - 1) / 2.0) * width
    ax.bar(
        x + offset, means, width=width, yerr=stds, capsize=2,
        label=LABELS[rt].replace("\n", " "),
        color=COLORS[idx], edgecolor="black", linewidth=0.5,
        error_kw={"elinewidth": 0.8}
    )

ax.set_yscale("log")
ax.set_ylabel("Latency per Operation (ns, log scale) — Lower is Better")
ax.set_xticks(x)
ax.set_xticklabels(OP_LABELS, fontsize=9.5)
ax.grid(axis="y", which="both", linestyle="--", alpha=0.35)
ax.legend(ncol=3, fontsize=8.5, loc="upper left", frameon=True)
plt.title("Fig. 5. OS Syscall and Virtual Memory Primitive Latency (Mean ± Std, 5 Trials)")
fig.tight_layout()
plt.savefig("results/figures/fig5_syscall_microbench.png", dpi=300)
plt.close()

# ----------------------------------------------------------------
# FIG 6: Container-to-Host Network RTT, Throughput & SOCK_RAW
# ----------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.2, 4.3))
x_rt = np.arange(len(ORDER))

rtt_m = net_summary["tcp_rtt_us_mean"].values
rtt_s = net_summary["tcp_rtt_us_std"].values
ax1.bar(x_rt, rtt_m, yerr=rtt_s, capsize=3, color=COLORS, edgecolor="black", linewidth=0.7)
ax1.set_title("(a) TCP Ping-Pong RTT (64 B, Lower is Better)")
ax1.set_ylabel("Round-Trip Time (µs)")
ax1.set_xticks(x_rt)
ax1.set_xticklabels([LABELS[rt] for rt in ORDER], fontsize=8.2)
ax1.set_ylim(0, max(rtt_m + rtt_s) * 1.22)
for i, (m, s) in enumerate(zip(rtt_m, rtt_s)):
    ax1.text(i, m + s + max(rtt_m)*0.03, f"{m:.1f}", ha="center", va="bottom", fontsize=8.2)

tp_m = net_summary["tcp_mb_s_mean"].values
tp_s = net_summary["tcp_mb_s_std"].values
raw_s = net_summary["sock_raw"].values
ax2.bar(x_rt, tp_m, yerr=tp_s, capsize=3, color=COLORS, edgecolor="black", linewidth=0.7)
ax2.set_title("(b) 32 MB TCP Throughput & SOCK_RAW Isolation")
ax2.set_ylabel("Throughput (MB/s) — Higher is Better")
ax2.set_xticks(x_rt)
ax2.set_xticklabels([LABELS[rt] for rt in ORDER], fontsize=8.2)
ax2.set_ylim(0, max(tp_m + tp_s) * 1.28)
for i, (m, s, rs) in enumerate(zip(tp_m, tp_s, raw_s)):
    tag = "RAW: BLK" if rs == "BLOCKED" else "RAW: EXP"
    color = "#1e8449" if rs == "BLOCKED" else "#922b21"
    ax2.text(i, m + s + max(tp_m)*0.025, f"{m:.0f}\n({tag})", ha="center", va="bottom", fontsize=7.8, fontweight="bold", color=color)

fig.suptitle("Fig. 6. Network Stack Latency, Throughput, and Raw Socket Isolation (Mean ± Std, 5 Trials)", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig6_network_overhead.png", dpi=300, bbox_inches="tight")
plt.close()

print("\n=== MODULE 1: SYSCALL MEAN (ns/op) ===")
print(sys_mean.round(1).to_string())
print("\n=== MODULE 1: SYSCALL SLOWDOWN VS BARE HOST (x) ===")
print((sys_mean.div(sys_mean.loc["host"])).round(2).to_string())
print("\n=== MODULE 1: NETWORK SUMMARY ===")
print(net_summary.to_string())
print("\nSaved fig5_syscall_microbench.png, fig6_network_overhead.png, and summary CSVs.")
