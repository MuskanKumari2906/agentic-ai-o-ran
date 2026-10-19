"""Figures for the report (docs/figures/*.png) from results/*.json. Missing inputs are skipped."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
OUT = ROOT / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": "#e5e7ea", "grid.linewidth": 0.6,
                     "axes.axisbelow": True, "figure.dpi": 180})
BLUE, RED, AMBER, GREEN, GREY = "#0b6fa4", "#c0392b", "#a86300", "#2e7d32", "#7a8594"
ORDER = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A5x"]


def load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def fig_e1(s):
    arms = s["e1"]["arms"]
    a = [x for x in ORDER if x in arms]
    f1 = np.array([arms[x]["f1"] for x in a])
    ci = np.array([arms[x]["f1_ci"] or [arms[x]["f1"]] * 2 for x in a])
    pr = [arms[x]["precision"] for x in a]
    rc = [arms[x]["recall"] for x in a]
    ex = [arms[x]["exact_match"] for x in a]
    fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.5))
    x = np.arange(len(a))
    ax[0].bar(x, f1, 0.6, color=[GREY if k in ("A0",) else BLUE for k in a])
    ax[0].errorbar(x, f1, yerr=[f1 - ci[:, 0], ci[:, 1] - f1], fmt="none", ecolor="#1c232b", capsize=3, lw=0.8)
    ax[0].set_xticks(x, a)
    ax[0].set_ylim(0, 1)
    ax[0].set_ylabel("violation F1 (95% bootstrap CI)")
    ax[0].set_title("Detection quality by arm", loc="left", fontsize=9.5)
    w = 0.27
    ax[1].bar(x - w, pr, w, label="precision", color=BLUE)
    ax[1].bar(x, rc, w, label="recall", color=AMBER)
    ax[1].bar(x + w, ex, w, label="exact-match accuracy", color=GREEN)
    ax[1].set_xticks(x, a)
    ax[1].set_ylim(0, 1.05)
    ax[1].legend(frameon=False, fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    ax[1].set_title("Precision, recall, exact match", loc="left", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "e1_quality.png")
    plt.close(fig)

    cats = ["clean", "vendor_default", "single", "multi", "decoy", "context", "noise"]
    bc = s["e1"]["by_category"]
    M = np.array([[bc.get(k, {}).get(c, np.nan) for c in cats] for k in a])
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    im = ax.imshow(M, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(cats)), [c.replace("_", " ") for c in cats], rotation=25, ha="right")
    ax.set_yticks(range(len(a)), a)
    ax.grid(False)
    for i in range(len(a)):
        for j in range(len(cats)):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{100 * M[i, j]:.0f}", ha="center", va="center", fontsize=7.5)
    ax.set_title("Exact-match accuracy (%) by configuration category", loc="left", fontsize=9.5)
    fig.colorbar(im, ax=ax, fraction=0.03)
    fig.tight_layout()
    fig.savefig(OUT / "e1_categories.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    for k in a:
        r = arms[k]
        ax.scatter(r["seconds_mean"], r["f1"], color=BLUE if k != "A0" else GREY, s=22)
        ax.annotate(k, (r["seconds_mean"], r["f1"]), textcoords="offset points", xytext=(4, 3), fontsize=8)
    ax.set_xlabel("seconds per configuration (local 7B, RTX 4060)")
    ax.set_ylabel("F1")
    ax.set_ylim(0, 1)
    ax.set_title("Quality vs. cost", loc="left", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "e1_cost.png")
    plt.close(fig)


def fig_e4(e4):
    arms = e4["arms"]
    a = list(arms)
    fig, ax = plt.subplots(1, 3, figsize=(10, 2.9))
    keys = [("unciphered_active_ue_hours", "unciphered active UE-hours", AMBER),
            ("spoofable_ue_hours", "UE-hours with RRC on NIA0", RED),
            ("remediation_outage_ue_hours", "outage caused by fixes (UE-h)", GREY)]
    for i, (k, t, c) in enumerate(keys):
        ax[i].bar(range(len(a)), [arms[x][k] for x in a], color=c)
        ax[i].set_xticks(range(len(a)), a)
        ax[i].set_title(t, loc="left", fontsize=9)
    fig.suptitle(f"E4: closed loop in the twin ({e4['hours']} h, identical seed per arm)", x=0.01, ha="left", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "e4_closed_loop.png")
    plt.close(fig)
    if e4.get("series"):
        fig, ax = plt.subplots(figsize=(7.5, 2.8))
        for k, ser in e4["series"].items():
            if k in ("none", "A0", "A3", "A5", "A7"):
                t = [r["t"] / 3600 for r in ser]
                ax.plot(t, [r["unciphered"] for r in ser], lw=1, label=k)
        ax.set_xlabel("simulated hours")
        ax.set_ylabel("active UEs on unciphered UP")
        ax.legend(frameon=False, fontsize=8, ncol=5)
        ax.set_title("Exposure over time", loc="left", fontsize=9.5)
        fig.tight_layout()
        fig.savefig(OUT / "e4_timeline.png")
        plt.close(fig)


def fig_e6(e6):
    P = e6["policies"]
    names = list(P)
    fig, ax = plt.subplots(1, 2, figsize=(8.5, 2.8))
    ax[0].bar(range(len(names)), [P[n]["exposure_ue_h"] for n in names], color=AMBER)
    ax[0].set_yscale("log")
    ax[0].set_title("exposure (UE-h, log)", loc="left", fontsize=9)
    ax[1].bar(range(len(names)), [P[n]["disruption_ue_h"] for n in names], color=GREY)
    ax[1].set_title("disruption (UE-h)", loc="left", fontsize=9)
    for a in ax:
        a.set_xticks(range(len(names)), [n.replace(" ", "\n") for n in names], fontsize=7.5)
    fig.suptitle("E6: remediation scheduling, mean over paired episodes", x=0.01, ha="left", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "e6_rl.png")
    plt.close(fig)


def fig_ns3(v):
    fig, ax = plt.subplots(figsize=(4.8, 3.0))
    for k, c in (("twin", BLUE), ("ns3", RED)):
        x = np.sort(np.array(v["sinr"][k]))
        ax.plot(x, np.arange(1, len(x) + 1) / len(x), color=c, lw=1.3,
                label="SecTwin" if k == "twin" else "ns-3 5G-LENA")
    ax.set_xlabel("downlink SINR (dB)")
    ax.set_ylabel("CDF")
    ax.legend(frameon=False)
    ax.set_title("Radio calibration: 19 sites, UMa, 500 m ISD, full load", loc="left", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "ns3_sinr_cdf.png")
    plt.close(fig)


if __name__ == "__main__":
    s = load("summary.json") or {}
    if s.get("e1", {}).get("arms"):
        fig_e1(s)
    if load("e4_twin.json"):
        fig_e4(load("e4_twin.json"))
    if load("e6_rl.json"):
        fig_e6(load("e6_rl.json"))
    if load("ns3_validation.json"):
        fig_ns3(load("ns3_validation.json"))
    print(sorted(p.name for p in OUT.glob("*.png")))
