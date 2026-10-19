"""Cross-check the twin's radio model against ns-3 5G-LENA on the same layout.

ns-3: contrib/nr example `cttc-nr-3gpp-calibration-user` (3GPP outdoor calibration), customConf,
UMa, 500 m ISD, 2 outer rings (19 sites, 57 sectors), 3.5 GHz, full-buffer downlink so every cell
transmits (full-load interference). Output: per-UE average SINR from the example's SQLite database.

Twin: identical layout and carrier, UEs dropped uniformly, serving cell = strongest RSRP,
interference with every cell at full load.

Differences that are expected and reported: 5G-LENA uses antenna arrays with beamforming and fast
fading; the twin uses a single 17 dBi sector element and no fast fading.
"""
import glob
import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sectwin.twin.radio import RadioMap, hex_sites  # noqa: E402

OUT_WIN = ROOT / "runs" / "ns3_out"
OUT_WSL = "/mnt/c/Users/abhij/Desktop/Pinnacle/oran-sectwin/runs/ns3_out"


def run_ns3(ue_per_gnb=5, gen_ms=300, seed_run=1):
    OUT_WIN.mkdir(parents=True, exist_ok=True)
    args = (f"cttc-nr-3gpp-calibration-user --configurationType=customConf --scenario=UMa --isd=500 "
            f"--numRings=2 --ueNumPergNb={ue_per_gnb} --freqScenario=1 --startingFreq=3.5e9 --bandwidth=20 "
            f"--gnbTxPower=42 --trafficScenario=0 --appGenerationTime=+{gen_ms}ms --technology=NR "
            f"--simTag=sectwin --outputDir={OUT_WSL} --RngRun={seed_run}")
    cmd = ["wsl", "--", "bash", "-lc", f"cd ~/sectwin-ns3/ns-3-dev && nice -n 15 ./ns3 run --no-build \"{args}\" 2>&1 | tail -25"]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"})
    print(r.stdout[-3000:], r.stderr[-2000:])


def read_ns3():
    sinr = []
    for db in glob.glob(str(OUT_WIN / "*.db")):
        con = sqlite3.connect(db)
        for (t,) in con.execute("select name from sqlite_master where type='table'"):
            if "sinr" in t.lower():
                cols = [c[1] for c in con.execute(f"pragma table_info({t})")]
                if "AvgSinr" in cols:
                    sinr += [r[0] for r in con.execute(f"select AvgSinr from {t}")]
        con.close()
    return np.array(sinr, dtype=float)


def twin_sinr(n_ue=2850, seed=3):
    rng = np.random.default_rng(seed)
    xy_sites = hex_sites(19, 500.0)
    rm = RadioMap(xy_sites, rng)
    r_cell = 500.0 / math.sqrt(3)
    pts = []
    while len(pts) < n_ue:
        p = rng.uniform(-1500, 1500, (4 * n_ue, 2))
        d = np.min(np.hypot(p[:, None, 0] - xy_sites[None, :, 0], p[:, None, 1] - xy_sites[None, :, 1]), axis=1)
        pts += list(p[(d < r_cell) & (d > 35.0)])     # 3GPP minimum UE-gNB 2D distance 35 m (UMa)
    xy = np.array(pts[:n_ue])
    rm.init_shadow(len(xy))
    rx = rm.rsrp(xy)
    serving = np.argmax(rx, axis=1)
    load = np.ones(rm.n_cells)
    return RadioMap.sinr(rx, serving, load, np.ones(rm.n_cells))


def main(run=True):
    if run:
        run_ns3()
    ns = read_ns3()
    tw = twin_sinr()
    if len(ns) == 0:
        print("no ns-3 SINR samples found")
        return
    q = lambda a, p: round(float(np.percentile(a, p)), 2)
    rows = {f"SINR p{p} (dB)": {"twin": q(tw, p), "ns3": q(ns, p)} for p in (5, 10, 50, 90, 95)}
    rows["SINR mean (dB)"] = {"twin": round(float(tw.mean()), 2), "ns3": round(float(ns.mean()), 2)}
    rows["samples"] = {"twin": int(len(tw)), "ns3": int(len(ns))}
    from scipy.stats import ks_2samp
    ks = ks_2samp(tw, ns)
    rows["KS distance"] = {"twin": round(float(ks.statistic), 3), "ns3": "-"}
    out = {"rows": rows, "sinr": {"twin": np.round(tw, 2).tolist(), "ns3": np.round(ns, 2).tolist()},
           "setup": "UMa, ISD 500 m, 19 sites / 57 sectors, 3.5 GHz, full load. ns-3.48 + 5G-LENA v5.1 "
                    "cttc-nr-3gpp-calibration-user (customConf, 20 MHz BWP, 42 dBm, saturation traffic)."}
    (ROOT / "results" / "ns3_validation.json").write_text(json.dumps(out))
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(run="--no-run" not in sys.argv)
