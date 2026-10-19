"""Train the PPO remediation scheduler and evaluate it against fixed policies (E6)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .env import RemediationEnv, policy_immediate, policy_threshold, policy_window

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "runs" / "rl_remediation_ppo.zip"


def evaluate(policy_fn, n=60, seed0=10_000):
    env = RemediationEnv()
    tot = {"exposure_ue_h": [], "disruption_ue_h": [], "reward": [], "pushes": []}
    for i in range(n):
        obs, _ = env.reset(seed=seed0 + i)
        done, R = False, 0.0
        while not done:
            obs, r, done, _, _ = env.step(policy_fn(obs, env))
            R += r
        for k in ("exposure_ue_h", "disruption_ue_h", "pushes"):
            tot[k].append(env.stats[k])
        tot["reward"].append(R)
    return {k: float(np.mean(v)) for k, v in tot.items()} | {"reward_std": float(np.std(tot["reward"]))}


def main(steps=300_000):
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    t0 = time.time()
    venv = make_vec_env(lambda: RemediationEnv(), n_envs=8, seed=1)
    model = PPO("MlpPolicy", venv, n_steps=512, batch_size=1024, learning_rate=3e-4, gamma=0.995,
                ent_coef=0.01, policy_kwargs={"net_arch": [128, 128]}, verbose=0, seed=1, device="cpu")
    model.learn(total_timesteps=steps)
    model.save(MODEL)
    train_s = time.time() - t0

    def rl(obs, env):
        a, _ = model.predict(obs, deterministic=True)
        return int(a)

    res = {"policies": {"immediate": evaluate(policy_immediate), "maintenance window": evaluate(policy_window),
                        "severity threshold": evaluate(policy_threshold), "PPO (learned)": evaluate(rl)},
           "train_steps": steps, "train_seconds": round(train_s, 1), "episodes": 60,
           "note": "Remediation-scheduling environment calibrated from the twin (users per site, diurnal "
                   "load, outage durations). Severity weights are a stated modelling choice."}
    (ROOT / "results" / "e6_rl.json").write_text(json.dumps(res, indent=1))
    return res


def paired_eval(n=200, seed0=20_000):
    """Paired comparison on identical episodes (same arrivals, sites, start hour)."""
    from stable_baselines3 import PPO
    model = PPO.load(MODEL, device="cpu")
    pols = {"immediate": policy_immediate, "maintenance window": policy_window,
            "severity threshold": policy_threshold,
            "PPO (learned)": lambda o, e: int(model.predict(o, deterministic=True)[0])}
    per = {k: {"reward": [], "exposure_ue_h": [], "disruption_ue_h": [], "pushes": []} for k in pols}
    for name, fn in pols.items():
        env = RemediationEnv()
        for i in range(n):
            obs, _ = env.reset(seed=seed0 + i)
            done, R = False, 0.0
            while not done:
                obs, r, done, _, _ = env.step(fn(obs, env))
                R += r
            per[name]["reward"].append(R)
            for k in ("exposure_ue_h", "disruption_ue_h", "pushes"):
                per[name][k].append(env.stats[k])
    rng = np.random.default_rng(0)
    out = {"policies": {}, "paired_vs_ppo": {}, "episodes": n}
    for k, v in per.items():
        out["policies"][k] = {m: float(np.mean(x)) for m, x in v.items()} | {"reward_std": float(np.std(v["reward"]))}
    ppo = np.array(per["PPO (learned)"]["reward"])
    for k, v in per.items():
        if k == "PPO (learned)":
            continue
        d = ppo - np.array(v["reward"])
        boots = [rng.choice(d, len(d)).mean() for _ in range(2000)]
        out["paired_vs_ppo"][k] = {"mean_reward_gain": float(d.mean()), "ci95": [float(np.percentile(boots, 2.5)),
                                   float(np.percentile(boots, 97.5))], "ppo_better_share": float((d > 0).mean())}
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "paired":
        print(json.dumps(paired_eval()["paired_vs_ppo"], indent=1))
    else:
        r = main(int(sys.argv[1]) if len(sys.argv) > 1 else 300_000)
        for k, v in r["policies"].items():
            print(f"{k:20s} exposure {v['exposure_ue_h']:8.2f} UE-h  disruption {v['disruption_ue_h']:6.2f} UE-h  "
                  f"reward {v['reward']:9.2f} +- {v['reward_std']:.1f}  pushes {v['pushes']:.1f}")
