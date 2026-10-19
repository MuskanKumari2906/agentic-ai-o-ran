"""Remediation scheduling environment (E6).

The SMO has a queue of verified fixes. Pushing a fix restarts security on that gNB, which drops
its users for the outage time (disruption). Waiting leaves the violation exposed (exposure).
Exposure and disruption both scale with the number of users on the site, which follows the
diurnal load profile, so the right decision depends on severity and time of day.

Calibration comes from the twin: users per site (n_ues / n_sites with a per-site factor),
diurnal profile (traffic.DIURNAL), outage durations (engine defaults: 20 s for algorithm /
DRB changes, 5 s for interface changes).

Severity weights (exposure cost per affected user-hour) are a stated modelling choice:
  high   (null ciphering or spoofable RRC, plaintext O1)   1.0
  medium (unprotected F1/N2/N3/Xn/E2, TLS < 1.2)           0.05
  low    (algorithm preference, TLS 1.2 under OSB-5)      0.004
Reward per step = -(sum of exposure) - DISRUPTION_WEIGHT * (user-hours of outage caused).
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ..twin.traffic import diurnal

SEV_W = np.array([1.0, 0.05, 0.004])          # high, medium, low
SEV_P = np.array([0.35, 0.40, 0.25])          # share of violations by severity
OUTAGE_S = np.array([20.0, 5.0, 20.0])        # algorithm-level for high/low, interface for medium
DISRUPTION_WEIGHT = 25.0
K = 8
STEP_MIN = 5.0

PARAM_SEVERITY = {
    "ciphering_algorithms": 0, "integrity_algorithms": 0, "drb_ciphering": 0, "o1_transport": 0,
    "f1c_protection": 1, "n2_protection": 1, "n3_protection": 1, "xn_protection": 1, "e2_protection": 1,
    "tls_min_version": 1, "drb_integrity": 2,
}


def item_features(sev: int, users: float, age_h: float, threat: float) -> list:
    one = [0.0, 0.0, 0.0]
    one[sev] = 1.0
    return one + [users / 150.0, min(age_h / 12.0, 2.0), threat, 1.0]


class RemediationEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, n_sites=19, n_ues=1500, rate_per_site_h=0.06, episode_h=24.0, seed=None):
        super().__init__()
        self.n_sites, self.n_ues = n_sites, n_ues
        self.rate = rate_per_site_h
        self.steps_per_ep = int(episode_h * 60 / STEP_MIN)
        self.observation_space = spaces.Box(-2, 3, shape=(3 + K * 7,), dtype=np.float32)
        self.action_space = spaces.Discrete(K + 1)       # 0 = wait, k = push pending item k-1
        self.rng = np.random.default_rng(seed)

    def _users(self, site, hour):
        return self.n_ues / self.n_sites * self.site_factor[site] * (0.25 + 0.75 * diurnal(hour)) / 0.9

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.hour = float(self.rng.uniform(0, 24))
        self.site_factor = self.rng.uniform(0.6, 1.4, self.n_sites)
        self.threat = self.rng.uniform(0.3, 1.0, self.n_sites)
        self.pending: list[dict] = []
        self.t = 0
        self.stats = {"exposure_ue_h": 0.0, "disruption_ue_h": 0.0, "pushes": 0}
        return self._obs(), {}

    def _obs(self):
        h = 2 * np.pi * self.hour / 24
        head = [np.sin(h), np.cos(h), diurnal(self.hour)]
        feats = []
        for it in self.pending[:K]:
            feats += item_features(it["sev"], self._users(it["site"], self.hour), it["age"], self.threat[it["site"]])
        feats += [0.0] * (K * 7 - len(feats))
        return np.array(head + feats, dtype=np.float32)

    def step(self, action):
        dt_h = STEP_MIN / 60.0
        reward = 0.0
        if 1 <= action <= min(K, len(self.pending)):
            it = self.pending.pop(action - 1)
            users = self._users(it["site"], self.hour)
            dis = users * OUTAGE_S[it["sev"]] / 3600.0
            self.stats["disruption_ue_h"] += dis
            self.stats["pushes"] += 1
            reward -= DISRUPTION_WEIGHT * dis
        exp = 0.0
        for it in self.pending:
            exp += SEV_W[it["sev"]] * self.threat[it["site"]] * self._users(it["site"], self.hour) * dt_h
            it["age"] += dt_h
        self.stats["exposure_ue_h"] += exp
        reward -= exp
        # new violations (verified fixes arriving from the compliance service)
        n_new = self.rng.poisson(self.rate * self.n_sites * dt_h)
        for _ in range(n_new):
            self.pending.append({"site": int(self.rng.integers(self.n_sites)),
                                 "sev": int(self.rng.choice(3, p=SEV_P)), "age": 0.0})
        self.pending.sort(key=lambda x: (x["sev"], -x["age"]))
        self.hour = (self.hour + dt_h) % 24
        self.t += 1
        done = self.t >= self.steps_per_ep
        return self._obs(), float(reward), done, False, {}


# ---------------------------------------------------------------- baseline policies (act on obs)
def _items(obs):
    out = []
    for k in range(K):
        f = obs[3 + 7 * k: 3 + 7 * (k + 1)]
        if f[6] > 0.5:
            out.append((k, int(np.argmax(f[:3]))))
    return out


def policy_immediate(obs, env):
    its = _items(obs)
    return its[0][0] + 1 if its else 0


def policy_window(obs, env):
    its = _items(obs)
    if not its:
        return 0
    return its[0][0] + 1 if 2.0 <= env.hour < 4.0 else 0


def policy_threshold(obs, env):
    """High severity: now. Medium: now unless in the evening peak. Low: maintenance window."""
    its = _items(obs)
    for k, sev in its:
        if sev == 0:
            return k + 1
        if sev == 1 and not (17.0 <= env.hour < 23.0):
            return k + 1
        if sev == 2 and 2.0 <= env.hour < 5.0:
            return k + 1
    return 0
