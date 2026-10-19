"""Labelled dataset of gNB configuration files.

Each item = (config text, deployment profile, oracle labels per security parameter).
Files are built from the OAI-style template with seeded mutations so that the dataset
is hard to pass by string matching alone (decoys and profile-dependent cases).

Categories
  clean            hardened settings, compliant under every profile
  vendor_default   the values OAI ships in its sample configs (nea0 / nia2,nia0 / drb_integrity no)
  single           one injected violation
  multi            two to four injected changes
  decoy            suspicious-looking values that are compliant under the item's profile
  context          same file as another item, evaluated under a different profile
  noise            non-security edits (radio parameters, extra settings) plus at most one change
"""
from __future__ import annotations

import copy
import json
import random
from dataclasses import asdict
from pathlib import Path

from ..conf.security import Profile, PROFILES, evaluate_text, summarize
from ..conf.template import GnbIdentity, SecuritySettings, render

SECURE = dict(
    ciphering_algorithms=["nea2", "nea1"], integrity_algorithms=["nia2", "nia1"],
    drb_ciphering="yes", drb_integrity="no", f1c_protection="dtls", n2_protection="ipsec",
    n3_protection="ipsec", xn_protection="ipsec", e2_protection="ipsec",
    o1_transport="netconf_tls", tls_min_version="1.3")

SECURE_VARIANTS = [
    {},
    {"ciphering_algorithms": ["nea3", "nea2", "nea1"], "integrity_algorithms": ["nia3", "nia2"]},
    {"ciphering_algorithms": ["nea2"], "integrity_algorithms": ["nia2", "nia3", "nia1"], "o1_transport": "netconf_ssh"},
    {"f1c_protection": "ipsec", "drb_integrity": "yes"},
    {"ciphering_algorithms": ["nea2", "nea3"], "xn_protection": "dtls", "n2_protection": "dtls"},
]

# (parameter, value, short tag). Whether a mutation is a violation depends on the profile.
MUTATIONS = [
    ("ciphering_algorithms", ["nea0"], "nea0_only"),
    ("ciphering_algorithms", ["nea0", "nea2"], "nea0_first"),
    ("ciphering_algorithms", ["nea2", "nea1", "nea0"], "nea0_last"),
    ("ciphering_algorithms", ["nea1", "nea2"], "nea1_first"),
    ("integrity_algorithms", ["nia2", "nia0"], "nia0_last"),
    ("integrity_algorithms", ["nia0", "nia2"], "nia0_first"),
    ("integrity_algorithms", ["nia0"], "nia0_only"),
    ("integrity_algorithms", ["nia1", "nia2"], "nia1_first"),
    ("drb_ciphering", "no", "drb_cipher_off"),
    ("drb_integrity", "no", "drb_integ_off"),
    ("f1c_protection", "none", "f1c_none"),
    ("n2_protection", "none", "n2_none"),
    ("n3_protection", "none", "n3_none"),
    ("xn_protection", "none", "xn_none"),
    ("e2_protection", "none", "e2_none"),
    ("o1_transport", "netconf_plain", "o1_plain"),
    ("tls_min_version", "1.1", "tls11"),
    ("tls_min_version", "1.0", "tls10"),
    ("tls_min_version", "1.2", "tls12"),
]

OAI_DEFAULT = {"ciphering_algorithms": ["nea0"], "integrity_algorithms": ["nia2", "nia0"],
               "drb_ciphering": "yes", "drb_integrity": "no"}

VENDORS = ["oai", "vendorA", "vendorB", "vendorC"]


def make_identity(rng: random.Random, idx: int) -> GnbIdentity:
    site = rng.choice(["CHN", "MAA", "BLR", "HYD", "CBE", "TRY"])
    return GnbIdentity(
        gnb_id=0xE00 + idx, name=f"gNB-{site}-{idx:03d}", tac=rng.randint(1, 40),
        nr_cellid=12345000 + idx * 16, pci=rng.randint(0, 1007),
        band=78, arfcn=rng.choice([620000, 630000, 641280, 650000]),
        amf_ip=f"10.{rng.randint(10, 60)}.0.{rng.randint(2, 250)}",
        ng_ip=f"10.{rng.randint(61, 99)}.{rng.randint(0, 255)}.{rng.randint(2, 250)}",
        vendor=rng.choice(VENDORS))


def _apply(base: dict, muts) -> dict:
    s = copy.deepcopy(base)
    for p, v, _ in muts:
        s[p] = copy.deepcopy(v)
    return s


def _item(item_id, cat, ident, settings, profile: Profile, muts, split, extra_params=None, note=""):
    text = render(ident, SecuritySettings(**settings), extra_params=extra_params)
    labels = evaluate_text(text, profile)
    return {
        "id": item_id, "category": cat, "split": split, "vendor": ident.vendor,
        "profile": asdict(profile), "mutations": [m[2] for m in muts], "note": note,
        "text": text,
        "labels": {p: l.to_dict() for p, l in labels.items()},
        "summary": summarize(labels),
        "identity": asdict(ident), "settings": settings,
    }


def build(seed: int = 7, n_target: int = 70, dev_fraction: float = 0.25) -> list[dict]:
    rng = random.Random(seed)
    items: list[dict] = []
    idx = 0

    def next_split():
        return "dev" if rng.random() < dev_fraction else "test"

    def base_secure():
        b = copy.deepcopy(SECURE)
        b.update(copy.deepcopy(rng.choice(SECURE_VARIANTS)))
        return b

    plan = (["clean"] * 7 + ["vendor_default"] * 5 + ["single"] * 14 + ["multi"] * 12 +
            ["decoy"] * 10 + ["noise"] * 6)
    rng.shuffle(plan)
    context_sources = []
    for cat in plan:
        idx += 1
        ident = make_identity(rng, idx)
        prof = rng.choice(PROFILES)
        muts = []
        extra = None
        if cat == "clean":
            settings = base_secure()
        elif cat == "vendor_default":
            settings = base_secure()
            settings.update(copy.deepcopy(OAI_DEFAULT))
            muts = [(k, v, "oai_default") for k, v in OAI_DEFAULT.items()][:0]
            muts = [("ciphering_algorithms", ["nea0"], "oai_default")]
        elif cat == "single":
            m = rng.choice(MUTATIONS)
            muts = [m]
            settings = _apply(base_secure(), muts)
        elif cat == "multi":
            k = rng.randint(2, 4)
            params_seen, muts = set(), []
            for m in rng.sample(MUTATIONS, len(MUTATIONS)):
                if m[0] not in params_seen:
                    muts.append(m)
                    params_seen.add(m[0])
                if len(muts) == k:
                    break
            settings = _apply(base_secure(), muts)
        elif cat == "decoy":
            # pick a mutation and a profile under which it is NOT a violation
            for _ in range(200):
                m = rng.choice(MUTATIONS)
                prof = rng.choice(PROFILES)
                settings = _apply(base_secure(), [m])
                txt = render(ident, SecuritySettings(**settings))
                if summarize(evaluate_text(txt, prof))["compliant"]:
                    muts = [m]
                    break
        elif cat == "noise":
            settings = base_secure()
            if rng.random() < 0.6:
                muts = [rng.choice(MUTATIONS)]
                settings = _apply(settings, muts)
            extra = {"sa_debug_mode": rng.choice([0, 1]), "maintenance_window": "02:00-04:00",
                     "thread_pool_size": rng.choice([4, 8]), "usrp_args": "type=b200"}
            ident.pci = rng.randint(0, 1007)
        it = _item(f"cfg-{idx:03d}", cat, ident, settings, prof, muts, next_split(), extra)
        items.append(it)
        if cat in ("vendor_default", "single", "multi", "decoy"):
            context_sources.append((it, ident, settings, muts, extra))

    # context-dependent pairs: same file, a profile that flips at least one verdict
    rng.shuffle(context_sources)
    made = 0
    for it, ident, settings, muts, extra in context_sources:
        if made >= max(0, n_target - len(items)):
            break
        base_prof = Profile(**it["profile"])
        text = it["text"]
        for prof in rng.sample(PROFILES, len(PROFILES)):
            if prof == base_prof:
                continue
            new = summarize(evaluate_text(text, prof))
            if set(new["violations"]) != set(it["summary"]["violations"]):
                idx += 1
                c = _item(f"cfg-{idx:03d}", "context", ident, settings, prof, muts, it["split"], extra,
                          note=f"same file as {it['id']} under a different profile")
                c["pair_of"] = it["id"]
                items.append(c)
                made += 1
                break
    return items


def save(items, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "configs").mkdir(exist_ok=True)
    for it in items:
        (out_dir / "configs" / f"{it['id']}.conf").write_text(it["text"], encoding="utf-8")
    with open(out_dir / "dataset.json", "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    stats = {}
    for it in items:
        s = stats.setdefault(it["category"], {"n": 0, "dev": 0, "test": 0, "noncompliant": 0, "violations": 0})
        s["n"] += 1
        s[it["split"]] += 1
        s["noncompliant"] += int(not it["summary"]["compliant"])
        s["violations"] += len(it["summary"]["violations"])
    with open(out_dir / "dataset_stats.json", "w") as f:
        json.dump(stats, f, indent=1)
    return stats


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    items = build()
    print(json.dumps(save(items, root / "data"), indent=1))
    print("total", len(items))
