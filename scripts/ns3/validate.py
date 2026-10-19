"""Cross-check the twin's radio model against ns-3 5G-LENA on the same layout.

ns-3: contrib/nr example `cttc-nr-3gpp-calibration-user` (3GPP outdoor calibration), customConf,
UMa, 500 m ISD, 2 outer rings (19 sites, 57 sectors), 3.5 GHz, full-buffer downlink so every cell
transmits (full-load interference). Output: per-slot SINR (linear) from the example's SQLite
database, averaged per UE in linear scale and converted to dB.

Two ns-3 configurations:
  default  5G-LENA defaults: antenna arrays with beamforming, fast fading
  matched  single antenna element at gNB and UE, omnidirectional beam, no fast fading
           (closest to the twin's single-sector-element, no-fast-fading model)

Twin: identical layout and carrier, UEs dropped uniformly, serving cell = strongest RSRP,
interference with every cell at full load.
"""
import collections
import glob
import json
import math
import os
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
CONFIGS = {
    "default": "",
    "matched": "--gnbNumRows=1 --gnbNumColumns=1 --ueNumRows=1 --ueNumColumns=1 --bfMethod=Omni --enableFading=0",
    "closest": "--attachToClosest=1",   # attach to the strongest/closest gNB, as the twin does
}


def run_ns3(tag, extra, ue_per_gnb=5, gen_ms=300, seed_run=1):
    (OUT_WIN / tag).mkdir(parents=True, exist_ok=True)
    args = (f"cttc-nr-3gpp-calibration-user --configurationType=customConf --scenario=UMa --isd=500 "
            f"--numRings=2 --ueNumPergNb={ue_per_gnb} --freqScenario=1 --startingFreq=3.5e9 --bandwidth=20 "
            f"--gnbTxPower=42 --trafficScenario=0 --appGenerationTime=+{gen_ms}ms --technology=NR "
            f"--simTag={tag} --outputDir={OUT_WSL}/{tag} --RngRun={seed_run} {extra}")
    cmd = ["wsl", "--", "bash", "-lc", f"cd ~/sectwin-ns3/ns-3-dev && nice -n 15 ./ns3 run --no-build \"{args}\" 2>&1 | tail -15"]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    print(tag, r.stdout[-2000:], r.stderr[-1000:], flush=True)


def read_ns3(tag):
    per = collections.defaultdict(list)
    for db in glob.glob(str(OUT_WIN / tag / "*.db")) + (glob.glob(str(OUT_WIN / "*.db")) if tag == "default" else []):
        con = sqlite3.connect(db)
        for c, r, s in con.execute("select CellId, Rnti, AvgSinr from sinr"):
            if s > 0:
                per[(c, r)].append(s)
        con.close()
    return np.array([10 * math.log10(np.mean(v)) for v in per.values()])


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
    return RadioMap.sinr(rx, serving, np.ones(rm.n_cells), np.ones(rm.n_cells))


def main(tags):
    for t in tags:
        run_ns3(t, CONFIGS[t])
    from scipy.stats import ks_2samp
    tw = twin_sinr()
    q = lambda a, p: round(float(np.percentile(a, p)), 1)
    series = {"twin": tw}
    for t in CONFIGS:
        s = read_ns3(t)
        if len(s):
            series[f"ns3_{t}"] = s
    rows = {}
    for p in (5, 10, 50, 90, 95):
        rows[f"SINR p{p} (dB)"] = {k: q(v, p) for k, v in series.items()}
    rows["SINR mean (dB)"] = {k: round(float(v.mean()), 1) for k, v in series.items()}
    rows["UEs"] = {k: int(len(v)) for k, v in series.items()}
    rows["KS distance to twin"] = {k: ("-" if k == "twin" else round(float(ks_2samp(tw, v).statistic), 3))
                                   for k, v in series.items()}
    out = {"rows": rows, "sinr": {k: np.round(v, 2).tolist() for k, v in series.items()},
           "setup": "UMa, ISD 500 m, 19 sites / 57 sectors, 3.5 GHz, full load. ns-3.48 + 5G-LENA v5.1 "
                    "cttc-nr-3gpp-calibration-user (customConf, 20 MHz BWP, 42 dBm, saturation traffic); "
                    "per-UE SINR = linear mean over slots, in dB."}
    (ROOT / "results" / "ns3_validation.json").write_text(json.dumps(out))
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a in CONFIGS])
