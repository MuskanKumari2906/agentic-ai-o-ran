"""Traffic models and diurnal load profile."""
from __future__ import annotations

import numpy as np

# name: (rate_bps while active, packet payload bytes, mean ON s, mean OFF s)
APPS = {
    "video": (8.0e6, 1400, 120.0, 300.0),
    "web":   (3.0e6, 1200, 5.0, 25.0),
    "voip":  (64e3, 100, 90.0, 400.0),
    "iot":   (4e3, 120, 1e9, 1.0),        # always on
    "bulk":  (30e6, 1400, 60.0, 600.0),
    "fwa":   (25e6, 1400, 1800.0, 1200.0),   # fixed-wireless-access CPE (home broadband over 5G)
}
APP_NAMES = list(APPS)
DEFAULT_MIX = {"video": 0.32, "web": 0.32, "voip": 0.12, "iot": 0.10, "bulk": 0.08, "fwa": 0.06}

# relative busy-hour profile of a mobile network (hour 0..23), peak 1.0 around 19-21h
DIURNAL = np.array([0.35, 0.25, 0.18, 0.15, 0.15, 0.20, 0.35, 0.55, 0.70, 0.75, 0.78, 0.80,
                    0.82, 0.80, 0.78, 0.80, 0.85, 0.90, 0.95, 1.00, 1.00, 0.90, 0.70, 0.50])

# queue limit in seconds of traffic: elastic TCP/QUIC flows keep standing queues short,
# VoIP de-jitter buffers drop late packets, IoT tolerates delay
BUFFER_S = {"video": 0.5, "web": 0.1, "voip": 0.2, "iot": 2.0, "bulk": 0.1, "fwa": 0.1}

# per-packet header bytes on the air interface (PDCP 18-bit SN, RLC, MAC subheader)
HDR_BYTES = 3 + 2 + 2
MAC_I_BYTES = 4      # PDCP integrity tag when user-plane integrity is active


def diurnal(hour: float) -> float:
    h0 = int(hour) % 24
    h1 = (h0 + 1) % 24
    f = hour - int(hour)
    return float(DIURNAL[h0] * (1 - f) + DIURNAL[h1] * f)


class TrafficState:
    def __init__(self, n: int, mix: dict, rng: np.random.Generator):
        names = list(mix)
        p = np.array([mix[k] for k in names], dtype=float)
        p /= p.sum()
        self.app = rng.choice([APP_NAMES.index(k) for k in names], size=n, p=p)
        self.rate = np.array([APPS[APP_NAMES[a]][0] for a in self.app])
        self.pkt = np.array([APPS[APP_NAMES[a]][1] for a in self.app], dtype=float)
        self.mean_on = np.array([APPS[APP_NAMES[a]][2] for a in self.app])
        self.mean_off = np.array([APPS[APP_NAMES[a]][3] for a in self.app])
        self.buffer_s = np.array([BUFFER_S[APP_NAMES[a]] for a in self.app])
        self.active = rng.random(n) < self.mean_on / (self.mean_on + self.mean_off)
        self.rng = rng

    def step(self, dt: float, load: float):
        r = self.rng.random(len(self.app))
        off_to_on = (~self.active) & (r < dt / self.mean_off * load)
        on_to_off = self.active & (r < dt / self.mean_on)
        self.active = (self.active | off_to_on) & ~on_to_off

    def demand_bits(self, dt: float) -> np.ndarray:
        return np.where(self.active, self.rate * dt, 0.0)
