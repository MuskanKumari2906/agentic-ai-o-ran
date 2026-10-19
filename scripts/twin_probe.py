"""Quick twin health check: KPIs, handover rate per mobility class, load."""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sectwin.twin.engine import ScenarioConfig, Twin  # noqa: E402

d = json.load(open(Path(__file__).resolve().parents[1] / "data" / "dataset.json"))
tw = Twin(ScenarioConfig(n_sites=19, drift_rate_per_site_hour=0.0), d)
t = time.time()
for _ in range(300):
    tw.step()
ho0 = tw.acc["handovers"]
srv0 = tw.serving.copy()
hos = np.zeros(tw.n)
for _ in range(600):
    prev = tw.serving.copy()
    tw.step()
    hos += (tw.serving != prev) & (prev >= 0) & (tw.serving >= 0)
print("900 ticks", round(time.time() - t, 1), "s")
s = tw.summary()
print({k: s[k] for k in ["throughput_gbps_mean", "latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "rlf",
                         "service_availability", "goodput_ratio"]})
for k, name in enumerate(["static", "pedestrian", "vehicular"]):
    m = tw.mob_kind == k
    print(name, "HO per UE-hour", round(hos[m].sum() / m.sum() * 6, 1), "mean speed", round(tw.speed[m].mean(), 1))
print("cell load mean/max", tw.cell_load.mean().round(3), tw.cell_load.max().round(3),
      "SINR p10/p50/p90", np.percentile(tw.last_sinr[tw.serving >= 0], [10, 50, 90]).round(1))
