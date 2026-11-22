#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

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

esc_df = pd.read_csv("results/module2_escapes.csv")
fb_df = pd.read_csv("results/module2_forkbomb.csv")
st_df = pd.read_csv("results/module2_starvation.csv")

# ----------------------------------------------------------------
# 1. Escape Suite v2 Summary + FIG 7
# ----------------------------------------------------------------
probes_only = esc_df[esc_df["probe"] != "SUMMARY"].copy()
probe_order = list(dict.fromkeys(probes_only["probe"].tolist()))
piv_esc = probes_only.pivot(index="probe", columns="runtime", values="status").reindex(index=probe_order, columns=ORDER)
mat_num = (piv_esc == "BLOCKED").astype(int)

summary_rows = esc_df[esc_df["probe"] == "SUMMARY"].set_index("runtime").reindex(ORDER)
esc_summary = pd.DataFrame({
    "blocked_count": mat_num.sum(axis=0),
    "total_probes": len(probe_order),
    "score_pct": (mat_num.sum(axis=0) / len(probe_order) * 100.0).round(1),
    "cap_count": summary_rows["detail"].str.replace("CAP_COUNT=", "", regex=False).astype(int),
})
esc_summary.to_csv("results/module2_escape_summary.csv")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 6.0), gridspec_kw={"width_ratios": [1.8, 1.0]})

cmap = ListedColormap(["#e74c3c", "#27ae60"])
ax1.imshow(mat_num.values, cmap=cmap, aspect="auto", vmin=0, vmax=1)
ax1.set_xticks(np.arange(len(ORDER)))
ax1.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.8)
ax1.set_yticks(np.arange(len(probe_order)))
ax1.set_yticklabels(probe_order, fontsize=8.2)
ax1.set_title("(a) 15-Probe Active Escape & Privilege Matrix")

for i in range(len(probe_order)):
    for j in range(len(ORDER)):
        val = piv_esc.iloc[i, j]
        txt = "BLK" if val == "BLOCKED" else "EXP"
        ax1.text(j, i, txt, ha="center", va="center", color="white", fontsize=7.8, fontweight="bold")

x = np.arange(len(ORDER))
scores = esc_summary["score_pct"].values
caps = esc_summary["cap_count"].values
bars = ax2.bar(x, scores, color=COLORS, edgecolor="black", linewidth=0.7)
ax2.set_ylim(0, 105)
ax2.set_xticks(x)
ax2.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.4)
ax2.set_ylabel("Blocked Probes (%)")
ax2.set_title("(b) Overall Score & Effective Capabilities")
ax2.grid(axis="y", linestyle="--", alpha=0.35)
for i, (sc, blk, cap) in enumerate(zip(scores, esc_summary["blocked_count"].values, caps)):
    ax2.text(i, sc + 2.5, f"{blk}/15\n({sc:.1f}%)\n{cap} caps", ha="center", va="bottom", fontsize=8.0, fontweight="bold")

fig.suptitle("Fig. 7. Expanded 15-Test Active Escape & Privilege Audit Across Five Runtimes", y=0.99)
fig.tight_layout()
plt.savefig("results/figures/fig7_escape_matrix_v2.png", dpi=300, bbox_inches="tight")
plt.close()

# ----------------------------------------------------------------
# 2. Fork-Bomb & Starvation Summaries + FIG 8
# ----------------------------------------------------------------
fb_summary = fb_df.groupby(["runtime", "mode"], as_index=False).agg(
    spawned_mean=("spawned_pids", "mean"),
    spawned_std=("spawned_pids", "std"),
    exit_code_mode=("exit_code", lambda s: int(s.mode().iloc[0])),
    outcome=("outcome", lambda s: s.mode().iloc[0]),
)
fb_summary["spawned_std"] = fb_summary["spawned_std"].fillna(0.0)
fb_summary.to_csv("results/module2_forkbomb_summary.csv", index=False)

st_summary = st_df.groupby(["runtime", "mode"], as_index=False).agg(
    host_mean_ms=("host_mean_ms", "mean"),
    host_ops_mean=("host_ops_sec", "mean"),
    util_mean=("host_utility_pct", "mean"),
    util_std=("host_utility_pct", "std"),
)
st_summary["util_std"] = st_summary["util_std"].fillna(0.0)
st_summary.to_csv("results/module2_starvation_summary.csv", index=False)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.5))
x = np.arange(len(ORDER))
w = 0.36

# Panel (a): Fork-Bomb
fb_unc = fb_summary[fb_summary["mode"] == "unconstrained"].set_index("runtime").reindex(ORDER)
fb_cap = fb_summary[fb_summary["mode"] == "capped_64pids"].set_index("runtime").reindex(ORDER)

unc_vals = fb_unc["spawned_mean"].fillna(0).values
cap_vals = fb_cap["spawned_mean"].fillna(0).values

ax1.bar(x - w/2, unc_vals, width=w, color="#c0392b", edgecolor="black", linewidth=0.7, label="Unconstrained (default)")
ax1.bar(x + w/2, cap_vals, width=w, color="#2e8b57", edgecolor="black", linewidth=0.7, label="Capped (pids.max = 64)")
ax1.axhline(64, color="#1e8449", linestyle="--", linewidth=1.0, alpha=0.8)
ax1.set_xticks(x)
ax1.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.4)
ax1.set_ylabel("Peak Child Processes Spawned (Target = 500)")
ax1.set_title("(a) Capped Fork-Bomb Containment (3 Trials)")
ax1.set_ylim(0, 580)
ax1.grid(axis="y", linestyle="--", alpha=0.35)
ax1.legend(fontsize=8.2, loc="upper right")

for i, rt in enumerate(ORDER):
    u = fb_unc.loc[rt, "spawned_mean"]
    ax1.text(i - w/2, u + 10, f"{u:.0f}", ha="center", va="bottom", fontsize=8.0, fontweight="bold")
    c = fb_cap.loc[rt, "spawned_mean"]
    outc = fb_cap.loc[rt, "outcome"]
    if pd.isna(c):
        ax1.text(i + w/2, 18, f"Killed\n({outc.replace('SANDBOX_', '')})", ha="center", va="bottom",
                 fontsize=7.6, fontweight="bold", color="#922b21")
    else:
        ax1.text(i + w/2, c + 10, f"{c:.0f}\n(EAGAIN)", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color="#1e8449")

# Panel (b): 8-Thread CPU Starvation
st_unc = st_summary[st_summary["mode"] == "unconstrained"].set_index("runtime").reindex(ORDER)
st_cap = st_summary[st_summary["mode"] == "capped_1cpu"].set_index("runtime").reindex(ORDER)

ax2.bar(x - w/2, st_unc["util_mean"].values, yerr=st_unc["util_std"].values, capsize=3,
        width=w, color="#d35400", edgecolor="black", linewidth=0.7, label="Unconstrained (8 threads)")
ax2.bar(x + w/2, st_cap["util_mean"].values, yerr=st_cap["util_std"].values, capsize=3,
        width=w, color="#2980b9", edgecolor="black", linewidth=0.7, label="Capped (--cpus=1 / cpu.max)")
ax2.axhline(100, color="gray", linestyle=":", linewidth=1.0)
ax2.set_xticks(x)
ax2.set_xticklabels([LABELS[r] for r in ORDER], fontsize=8.4)
ax2.set_ylabel("4-Worker Host CPU Utility (%) — Higher is Better")
ax2.set_title("(b) 8-Thread CPU Starvation Impact (Mean ± Std, 3 Trials)")
ax2.set_ylim(0, 115)
ax2.grid(axis="y", linestyle="--", alpha=0.35)
ax2.legend(fontsize=8.2, loc="lower right")

for i in range(len(ORDER)):
    um, us = st_unc["util_mean"].iloc[i], st_unc["util_std"].iloc[i]
    cm, cs = st_cap["util_mean"].iloc[i], st_cap["util_std"].iloc[i]
    ax2.text(i - w/2, um + us + 2.0, f"{um:.1f}%", ha="center", va="bottom", fontsize=7.8, fontweight="bold")
    ax2.text(i + w/2, cm + cs + 2.0, f"{cm:.1f}%", ha="center", va="bottom", fontsize=7.8, fontweight="bold")

fig.suptitle("Fig. 8. Concurrency Blast Radius: Fork-Bomb Containment and 8-Thread CPU Starvation", y=1.01)
fig.tight_layout()
plt.savefig("results/figures/fig8_forkbomb_and_starvation.png", dpi=300, bbox_inches="tight")
plt.close()

print("\n=== MODULE 2: 15-TEST ESCAPE SUMMARY ===")
print(esc_summary.to_string())
print("\n=== MODULE 2: FORK-BOMB SUMMARY ===")
print(fb_summary.to_string(index=False))
print("\n=== MODULE 2: CPU STARVATION SUMMARY ===")
print(st_summary.round(2).to_string(index=False))
print("\nSaved fig7_escape_matrix_v2.png, fig8_forkbomb_and_starvation.png, and summary CSVs.")
