"""Use the trained PPO scheduler inside the twin (remediation_policy = "rl")."""
from __future__ import annotations

import numpy as np

from .env import K, PARAM_SEVERITY, item_features
from ..twin.traffic import diurnal
from .train import MODEL


class RLPolicy:
    name = "rl"

    def __init__(self, model):
        self.model = model
        self.decided_t = -1e9
        self.allowed: set[int] = set()

    @classmethod
    def load(cls):
        from stable_baselines3 import PPO
        return cls(PPO.load(MODEL, device="cpu"))

    def _decide(self, twin):
        ready = [p for p in twin.pending_pushes if twin.t >= p["ready_t"]]
        items = []
        for p in ready:
            sev = min(PARAM_SEVERITY.get(k, 1) for k in p["fixes"]) if p["fixes"] else 2
            site = p["site"]
            users = float(((twin.serving >= 0) & (twin.radio.cell_site[np.maximum(twin.serving, 0)] == site)).sum())
            users *= 1500.0 / max(twin.n, 1)          # policy trained at 1500 UEs / 19 sites
            threat = 1.0 if twin.attackers else 0.5
            items.append((sev, -((twin.t - p["created_t"]) / 3600.0), p, users, threat))
        items.sort(key=lambda x: (x[0], x[1]))
        h = 2 * np.pi * twin.hour / 24
        feats = [np.sin(h), np.cos(h), diurnal(twin.hour)]
        for sev, negage, p, users, threat in items[:K]:
            feats += item_features(sev, users, -negage, threat)
        feats += [0.0] * (3 + K * 7 - len(feats))
        a, _ = self.model.predict(np.array(feats, dtype=np.float32), deterministic=True)
        a = int(a)
        self.allowed = {id(items[a - 1][2])} if 1 <= a <= len(items[:K]) else set()

    def allow(self, twin, push) -> bool:
        if twin.t - self.decided_t >= 300.0:     # one decision per 5 simulated minutes, as in training
            self._decide(twin)
            self.decided_t = twin.t
        if id(push) in self.allowed:
            self.allowed.discard(id(push))
            return True
        return False
