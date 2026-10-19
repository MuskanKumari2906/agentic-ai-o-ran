"""Check common random numbers: the drift-event sequence must not depend on what the agent fixed."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sectwin.twin.engine import ScenarioConfig, Twin  # noqa: E402

data = [x for x in json.load(open(Path(__file__).resolve().parents[1] / "data" / "dataset.json")) if x["split"] == "test"]


def run(fix):
    tw = Twin(ScenarioConfig(n_sites=7, n_ues=300, drift_rate_per_site_hour=3, seed=5,
                             attackers=[{"kind": "o1_mitm", "rate_per_hour": 5}]), data)
    for i in range(900):
        tw.step()
        if fix and i == 300:
            for s in tw.sites:
                tw.push(s.idx, {"o1_transport": "netconf_ssh"}, "test")
    return [(e["t"], e["site"], e["item"]) for e in tw.event_log
            if e["kind"] == "config_change" and e.get("cause") != "o1_mitm"], tw.acc["remediation_reselections"]


a, _ = run(False)
b, resel = run(True)
print("drift events", len(a), len(b), "identical:", a == b, "| reselections from pushes:", resel)
