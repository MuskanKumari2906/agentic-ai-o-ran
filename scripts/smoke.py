"""Smoke test: run selected arms on a few dataset items and print outcome vs oracle."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sectwin.agents.pipeline import Pipeline  # noqa: E402
from sectwin.conf.security import Profile  # noqa: E402
from sectwin.retrieval.index import ClauseIndex  # noqa: E402

ids = sys.argv[1].split(",") if len(sys.argv) > 1 else ["cfg-005", "cfg-001"]
arms = sys.argv[2].split(",") if len(sys.argv) > 2 else ["A3", "A5"]
data = {d["id"]: d for d in json.load(open(Path(__file__).resolve().parents[1] / "data" / "dataset.json"))}
t = time.time()
idx = ClauseIndex()
print("index built", round(time.time() - t, 1), "s", flush=True)
pipe = Pipeline(idx)
for i in ids:
    it = data[i]
    for arm in arms:
        r = pipe.run(arm, i, it["text"], Profile(**it["profile"]))
        print(f"{i} {arm}: truth={it['summary']['violations']} pred={r.predicted_violations} "
              f"fixes={r.fixes} rounds={len(r.rounds)} esc={r.escalated} {r.seconds:.0f}s tok={r.tokens} err={r.error}",
              flush=True)
        for rd in r.rounds:
            print("   round", rd["round"], "issues:", [(x["type"], x["parameter"]) for x in rd["issues"]],
                  "critic:", [(c.get("type"), c.get("parameter"), c.get("accepted")) for c in rd["critic"]], flush=True)
