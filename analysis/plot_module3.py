#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

os.makedirs("results/figures", exist_ok=True)

ORDER = ["docker", "podman", "containerd", "gvisor", "lxc"]
LABELS = {
    "docker": "Docker\n(runc)",
    "podman": "Podman\n(rootless)",
    "containerd": "containerd\n(nerdctl)",
    "gvisor": "gVisor\n(runsc)",
    "lxc": "LXC\n(system)"
}
SHORT_LABELS = {
    "docker": "Docker",
    "podman": "Podman",
    "containerd": "containerd",
    "gvisor": "gVisor",
    "lxc": "LXC"
}
COLORS = ["#2b5c8f", "#2e8b57", "#4f81bd", "#c0392b", "#7f8c8d"]

plt.rcParams.update({
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "figure.dpi": 300,
})

# Load verified datasets
poll_df = pd.read_csv("results/arena_results.csv")
ebpf_df = pd.read_csv("results/module3_ebpf_arena.csv")
p1_sum = pd.read_csv("results/summary_table.csv", index_col=0).reindex(ORDER)
m1_sys = pd.read_csv("results/module1_syscall_summary.csv", index_col=0).reindex(ORDER)
m1_net = pd.read_csv("results/module1_net_summary.csv", index_col=0).reindex(ORDER)
m2_esc = pd.read_csv("results/module2_escape_summary.csv", index_col=0).reindex(ORDER)

# ----------------------------------------------------------------
# 1. Polling vs. eBPF Comparison Summary + FIG 9
# ----------------------------------------------------------------
comp_rows = []
for rt in ORDER:
    p_sub = poll_df[poll_df["runtime"] == rt]
    p_det = p_sub[p_sub["detected"] == True]
    e_sub = ebpf_df[ebpf_df["runtime"] == rt]
    e_det = e_sub[e_sub["detected"] == True]
    e_g3 = e_sub[e_sub["gen"] == 3]

    comp_rows.append({
        "runtime": rt,
        "poll_det_pct": round(p_sub["detected"].mean() * 100.0, 1),
        "poll_mttd_ms": round(p_det["mttd_ms"].mean(), 1) if len(p_det) else np.nan,
        "poll_resp_ms": round(p_det["total_response_ms"].mean(), 1) if len(p_det) else np.nan,
        "poll_resp_std": round(p_det["total_response_ms"].std(), 1) if len(p_det) else 0.0,
        "ebpf_det_pct": round(e_sub["detected"].mean() * 100.0, 1),
        "ebpf_kern_mttd_ms": round(e_det["kernel_mttd_ms"].mean(), 2) if len(e_det) else np.nan,
        "ebpf_kern_mttd_std": round(e_det["kernel_mttd_ms"].std(), 2) if len(e_det) else 0.0,
        "ebpf_launch_mttd_ms": round(e_det["mttd_from_launch_ms"].mean(), 1) if len(e_det) else np.nan,
        "ebpf_kill_ms": round(e_det["kill_ms"].mean(), 1) if len(e_det) else np.nan,
        "ebpf_resp_ms": round(e_det["total_response_ms"].mean(), 1) if len(e_det) else np.nan,
        "ebpf_resp_std": round(e_det["total_response_ms"].std(), 1) if len(e_det) else 0.0,
        "ebpf_g3_spoof_pct": round(e_g3["prctl_spoof_seen"].mean() * 100.0, 1),
    })

comp_df = pd.DataFrame(comp_rows).set_index("runtime").reindex(ORDER)
comp_df["resp_speedup_x"] = (comp_df["poll_resp_ms"] / comp_df["ebpf_resp_ms"]).round(2)
comp_df.to_csv("results/module3_blueteam_comparison.csv")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.4))
x = np.arange(len(ORDER))
w = 0.36

ax1.bar(x - w/2, comp_df["poll_det_pct"], width=w, color="#2980b9", edgecolor="black", linewidth=0.7, label="User-Space Polling (psutil)")
ax1.bar(x + w/2, comp_df["ebpf_det_pct"], width=w, color="#27ae60", edgecolor="black", linewidth=0.7, label="Kernel eBPF (bpftrace)")
ax1.set_xticks(x)
ax1.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.5)
ax1.set_ylabel("Detection Rate (%) — 27 Trials per Runtime")
ax1.set_title("(a) Malware Detection Rate: Polling vs. Kernel eBPF")
ax1.set_ylim(0, 118)
ax1.grid(axis="y", linestyle="--", alpha=0.35)
ax1.legend(fontsize=8.3, loc="lower left")

for i in range(len(ORDER)):
    pv = comp_df["poll_det_pct"].iloc[i]
    ev = comp_df["ebpf_det_pct"].iloc[i]
    ax1.text(i - w/2, pv + 2, f"{pv:.1f}%", ha="center", va="bottom", fontsize=7.8, fontweight="bold")
    ax1.text(i + w/2, ev + 2, f"{ev:.1f}%", ha="center", va="bottom", fontsize=7.8, fontweight="bold",
             color="#922b21" if ev == 0 else "black")

poll_r = comp_df["poll_resp_ms"].fillna(0).values
ebpf_r = comp_df["ebpf_resp_ms"].fillna(0).values
ax2.bar(x - w/2, poll_r, width=w, color="#2980b9", edgecolor="black", linewidth=0.7, label="User-Space Polling (total)")
ax2.bar(x + w/2, ebpf_r, width=w, color="#27ae60", edgecolor="black", linewidth=0.7, label="Kernel eBPF (total)")
ax2.set_xticks(x)
ax2.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.5)
ax2.set_ylabel("Mean End-to-End Response Time (ms) — Lower is Better")
ax2.set_title("(b) Total Containment Latency (Launch to Kill)")
ax2.set_ylim(0, max(poll_r) * 1.18)
ax2.grid(axis="y", linestyle="--", alpha=0.35)
ax2.legend(fontsize=8.3, loc="upper left")

for i, rt in enumerate(ORDER):
    pv = comp_df.loc[rt, "poll_resp_ms"]
    ev = comp_df.loc[rt, "ebpf_resp_ms"]
    sp = comp_df.loc[rt, "resp_speedup_x"]
    ax2.text(i - w/2, pv + 90, f"{pv:.0f}", ha="center", va="bottom", fontsize=7.8, fontweight="bold")
    if pd.isna(ev):
        ax2.text(i + w/2, 160, "Blind\n(0%)", ha="center", va="bottom", fontsize=7.8, fontweight="bold", color="#922b21")
    else:
        ax2.text(i + w/2, ev + 90, f"{ev:.0f}\n({sp:.1f}x)", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color="#1e8449")

fig.suptitle("Fig. 9. Dual Blue Team Showdown Across Five Runtimes (135 Polling vs. 135 eBPF Trials)", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig9_ebpf_vs_polling.png", dpi=300, bbox_inches="tight")
plt.close()

# ----------------------------------------------------------------
# 2. Gen 1 vs. Gen 2 vs. Gen 3 Evasion Curves + FIG 10
# ----------------------------------------------------------------
gen_poll = poll_df[poll_df["detected"] == True].pivot_table(
    index=["virus", "gen"], columns="runtime", values="mttd_ms", aggfunc="mean"
).reindex(columns=ORDER)
gen_poll.round(1).to_csv("results/module3_gen_evasion_polling.csv")

gen_ebpf = ebpf_df[ebpf_df["detected"] == True].pivot_table(
    index=["virus", "gen"], columns="runtime", values="kernel_mttd_ms", aggfunc="mean"
).reindex(columns=ORDER)
gen_ebpf.round(2).to_csv("results/module3_gen_evasion_ebpf.csv")

fig, axes = plt.subplots(1, 3, figsize=(12.2, 4.0), sharey=False)
viruses = [("cpu_virus", "(a) CPU Virus (Polling MTTD)"),
           ("mem_virus", "(b) Memory Virus (Polling MTTD)"),
           ("io_virus", "(c) Disk I/O Virus (Polling MTTD)")]
markers = ["o", "s", "^", "D", "v"]

for ax, (vname, title) in zip(axes, viruses):
    sub = poll_df[(poll_df["virus"] == vname) & (poll_df["detected"] == True)]
    for idx, rt in enumerate(ORDER):
        rt_sub = sub[sub["runtime"] == rt].groupby("gen")["mttd_ms"].agg(["mean", "std"]).reindex([1, 2, 3])
        if rt_sub["mean"].notna().any():
            ax.errorbar(
                [1, 2, 3], rt_sub["mean"].values, yerr=rt_sub["std"].fillna(0).values,
                marker=markers[idx], color=COLORS[idx], linewidth=1.8, capsize=3,
                label=SHORT_LABELS[rt]
            )
    ax.set_title(title, fontsize=10.2)
    ax.set_xticks([1, 2, 3])
    ax.set_xticklabels(["Gen 1\n(Baseline)", "Gen 2\n(Stealth)", "Gen 3\n(Camouflage)"], fontsize=8.5)
    ax.grid(True, linestyle="--", alpha=0.35)
    if vname == "cpu_virus":
        ax.set_ylabel("Polling MTTD (ms, Mean ± Std)")
    if vname == "io_virus":
        ax.text(2.0, ax.get_ylim()[1] * 0.85, "gVisor: 0/9 detected\n(tmpfs /tmp blind spot)",
                ha="center", va="top", fontsize=7.8, color="#922b21",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#fdecea", edgecolor="#c0392b", alpha=0.9))

handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=5, bbox_to_anchor=(0.5, -0.06), frameon=True, fontsize=8.8)
fig.suptitle("Fig. 10. Multi-Generational Evasion Curves Under User-Space Polling (Gen 1 → Gen 3)", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig10_gen_evasion_curves.png", dpi=300, bbox_inches="tight")
plt.close()

# ----------------------------------------------------------------
# 3. Transparent 5-Dimension Weighted Decision Matrix + FIG 11
# ----------------------------------------------------------------
# All 5 dimensions normalized strictly from empirical CSV measurements onto [0, 100]:
# D1. Security Isolation: exact 15-probe blocked percentage (module2_escape_summary.csv)
d1_sec = m2_esc["score_pct"]

# D2. Syscall & Disk I/O Speed: 50% inverse syscall geometric-mean slowdown + 50% normalized disk I/O
sys_cols = ["getpid_vs_host_x", "open_close_vs_host_x", "pipe_rw_vs_host_x",
            "mmap_fault_unmap_vs_host_x", "fork_wait_vs_host_x"]
sys_geomean = np.exp(np.log(m1_sys[sys_cols]).mean(axis=1))
sys_score = (sys_geomean.min() / sys_geomean) * 100.0
io_score = (p1_sum["Disk_IO_MB_s"] / p1_sum["Disk_IO_MB_s"].max()) * 100.0
d2_sysio = 0.5 * sys_score + 0.5 * io_score

# D3. Network Performance: 50% normalized TCP throughput + 50% inverse normalized TCP RTT
net_tp = (m1_net["tcp_mb_s_mean"] / m1_net["tcp_mb_s_mean"].max()) * 100.0
net_rtt = (m1_net["tcp_rtt_us_mean"].min() / m1_net["tcp_rtt_us_mean"]) * 100.0
d3_net = 0.5 * net_tp + 0.5 * net_rtt

# D4. Resource Efficiency (Startup & RAM): 50% inverse startup + 50% inverse idle RAM
st_score = (p1_sum["Startup_ms"].min() / p1_sum["Startup_ms"]) * 100.0
ram_score = (p1_sum["Idle_RAM_MB"].min() / p1_sum["Idle_RAM_MB"]) * 100.0
d4_eff = 0.5 * st_score + 0.5 * ram_score

# D5. Blue Team Observability: 50% Polling Detection (%) + 50% eBPF Detection (%)
d5_obs = 0.5 * comp_df["poll_det_pct"] + 0.5 * comp_df["ebpf_det_pct"]

dims = pd.DataFrame({
    "Security_Isolation": d1_sec.round(1),
    "Syscall_Disk_IO": d2_sysio.round(1),
    "Network_Perf": d3_net.round(1),
    "Startup_RAM_Eff": d4_eff.round(1),
    "BlueTeam_Obs": d5_obs.round(1),
}, index=ORDER)

# Three weighted deployment profiles (weights sum to 1.00)
profiles = {
    "General_EDR":        {"Security_Isolation": 0.30, "Syscall_Disk_IO": 0.20, "Network_Perf": 0.15, "Startup_RAM_Eff": 0.15, "BlueTeam_Obs": 0.20},
    "High_Throughput":    {"Security_Isolation": 0.15, "Syscall_Disk_IO": 0.25, "Network_Perf": 0.35, "Startup_RAM_Eff": 0.15, "BlueTeam_Obs": 0.10},
    "Security_First":     {"Security_Isolation": 0.55, "Syscall_Disk_IO": 0.15, "Network_Perf": 0.05, "Startup_RAM_Eff": 0.10, "BlueTeam_Obs": 0.15},
}

prof_scores = pd.DataFrame(index=ORDER)
for pname, wdict in profiles.items():
    prof_scores[pname] = sum(dims[col] * wt for col, wt in wdict.items()).round(1)

full_matrix = pd.concat([dims, prof_scores], axis=1)
full_matrix.to_csv("results/module3_decision_matrix.csv")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.6, 4.6), gridspec_kw={"width_ratios": [1.15, 1.0]})

# Panel (a): Normalized Dimension Heatmap
dim_cols = list(dims.columns)
dim_labels = ["Security\n(15-Probe)", "Syscall &\nDisk I/O", "Network\n(TCP)", "Startup &\nIdle RAM", "Blue Team\n(Poll+eBPF)"]
im = ax1.imshow(dims.values, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
ax1.set_xticks(np.arange(len(dim_cols)))
ax1.set_xticklabels(dim_labels, fontsize=8.4)
ax1.set_yticks(np.arange(len(ORDER)))
ax1.set_yticklabels([SHORT_LABELS[r] for r in ORDER], fontsize=9.0, fontweight="bold")
ax1.set_title("(a) Normalized Empirical Dimension Scores (0–100)")

for i in range(len(ORDER)):
    for j in range(len(dim_cols)):
        val = dims.iloc[i, j]
        txt_col = "white" if (val < 30 or val > 85) else "black"
        ax1.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8.5, fontweight="bold", color=txt_col)

# Panel (b): Weighted Profile Scores
xp = np.arange(len(ORDER))
wp = 0.25
p_defs = [
    ("General_EDR", "General / EDR-Monitored", "#2b5c8f"),
    ("High_Throughput", "High-Throughput Services", "#d35400"),
    ("Security_First", "Security-First Sandbox", "#27ae60"),
]
for idx, (col, lbl, colr) in enumerate(p_defs):
    offset = (idx - 1) * wp
    vals = prof_scores[col].values
    ax2.bar(xp + offset, vals, width=wp, color=colr, edgecolor="black", linewidth=0.6, label=lbl)
    for j, v in enumerate(vals):
        ax2.text(j + offset, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=7.2, fontweight="bold")

ax2.set_xticks(xp)
ax2.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.3)
ax2.set_ylabel("Weighted Composite Score (0–100)")
ax2.set_title("(b) Deployment Profile Rankings")
ax2.set_ylim(0, 105)
ax2.grid(axis="y", linestyle="--", alpha=0.35)
ax2.legend(fontsize=7.8, loc="upper right")

fig.suptitle("Fig. 11. Empirical Multi-Criteria Decision Matrix Across Five Linux Container Runtimes", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig11_weighted_decision_matrix.png", dpi=300, bbox_inches="tight")
plt.close()

print("\n=== MODULE 3: POLLING VS. EBPF COMPARISON ===")
print(comp_df[["poll_det_pct", "poll_mttd_ms", "poll_resp_ms", "ebpf_det_pct", "ebpf_kern_mttd_ms", "ebpf_resp_ms", "resp_speedup_x", "ebpf_g3_spoof_pct"]].to_string())
print("\n=== MODULE 3: POLLING MTTD BY VIRUS & GEN (ms) ===")
print(gen_poll.round(1).to_string())
print("\n=== MODULE 3: EBPF KERNEL MTTD BY VIRUS & GEN (ms) ===")
print(gen_ebpf.round(2).to_string())
print("\n=== FINAL WEIGHTED DECISION MATRIX (0-100) ===")
print(full_matrix.to_string())
print("\nSaved fig9, fig10, fig11 and summary CSVs.")
