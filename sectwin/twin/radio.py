"""Radio layer of the twin: hexagonal macro layout, 3GPP TR 38.901 UMa path loss, sector
antenna pattern, correlated shadowing, SINR, and an NR-like link abstraction.

Simplifications (documented in docs/TWIN.md):
* LOS/NLOS: path loss is the LOS-probability-weighted mix of the UMa LOS and NLOS
  (optional model) formulas, in dB, instead of a random LOS state per link.
* Link abstraction: attenuated Shannon, 0.75*log2(1+SINR), capped at 7.4 b/s/Hz
  (~256QAM r=948/1024), zero below -6.5 dB, rank 2 above 12 dB SINR, 14 % L1/L2 overhead.
* Downlink only. No fast fading (average over the tick).
"""
from __future__ import annotations

import math

import numpy as np

FC_GHZ = 3.5
BW_HZ = 100e6
TX_DBM = 49.0           # per sector, 100 MHz (80 W class macro)
ANT_GAIN_DBI = 17.0
H_BS, H_UT = 25.0, 1.5
NOISE_DBM = -174 + 10 * math.log10(BW_HZ) + 7.0   # UE noise figure 7 dB
SHADOW_SIGMA_DB = 6.0
SHADOW_DECORR_M = 50.0
SHADOW_INTERSITE_CORR = 0.5     # TR 38.901 inter-site shadow fading correlation
SECTOR_AZ = np.deg2rad([30.0, 150.0, 270.0])
OVERHEAD = 0.14


def hex_sites(n: int, isd: float) -> np.ndarray:
    """First n sites of a hexagonal spiral (axial coords), metres."""
    coords = [(0, 0)]
    dirs = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
    ring = 1
    while len(coords) < n:
        q, r = -ring, ring        # start corner
        for d in range(6):
            for _ in range(ring):
                coords.append((q, r))
                q, r = q + dirs[d][0], r + dirs[d][1]
        ring += 1
    coords = coords[:n]
    xy = np.array([[isd * (q + r / 2.0), isd * (r * math.sqrt(3) / 2.0)] for q, r in coords])
    return xy


def pathloss_db(d2d: np.ndarray) -> np.ndarray:
    d2d = np.maximum(d2d, 10.0)
    d3d = np.sqrt(d2d ** 2 + (H_BS - H_UT) ** 2)
    pl_los = 28.0 + 22.0 * np.log10(d3d) + 20.0 * math.log10(FC_GHZ)
    pl_nlos = np.maximum(pl_los, 32.4 + 20.0 * math.log10(FC_GHZ) + 30.0 * np.log10(d3d))
    p_los = np.where(d2d <= 18.0, 1.0, 18.0 / d2d + np.exp(-d2d / 63.0) * (1 - 18.0 / d2d))
    return p_los * pl_los + (1 - p_los) * pl_nlos


def sector_gain_db(angle_off: np.ndarray) -> np.ndarray:
    """3GPP horizontal pattern: -min(12 (phi/65deg)^2, 30) dB."""
    phi = np.rad2deg(np.abs((angle_off + np.pi) % (2 * np.pi) - np.pi))
    return -np.minimum(12.0 * (phi / 65.0) ** 2, 30.0)


def spectral_efficiency(sinr_db: np.ndarray) -> np.ndarray:
    lin = 10 ** (sinr_db / 10.0)
    se = np.minimum(7.4, 0.75 * np.log2(1 + lin))
    se = np.where(sinr_db < -6.5, 0.0, se)
    rank = np.where(sinr_db > 12.0, 2.0, 1.0)
    return se * rank


def full_rate_bps(sinr_db: np.ndarray) -> np.ndarray:
    return spectral_efficiency(sinr_db) * BW_HZ * (1 - OVERHEAD)


class RadioMap:
    """Per-tick link budget for all UE x cell pairs."""

    def __init__(self, site_xy: np.ndarray, rng: np.random.Generator):
        self.site_xy = site_xy
        self.n_sites = len(site_xy)
        self.n_cells = 3 * self.n_sites
        self.cell_site = np.repeat(np.arange(self.n_sites), 3)
        self.cell_az = np.tile(SECTOR_AZ, self.n_sites)
        self.rng = rng
        self.shadow = None

    def _draw(self, n_ue: int) -> np.ndarray:
        """Shadowing with 0.5 correlation between sites: common + per-site component."""
        a = np.sqrt(SHADOW_INTERSITE_CORR)
        b = np.sqrt(1 - SHADOW_INTERSITE_CORR)
        common = self.rng.normal(0, SHADOW_SIGMA_DB, (n_ue, 1))
        return a * common + b * self.rng.normal(0, SHADOW_SIGMA_DB, (n_ue, self.n_sites))

    def init_shadow(self, n_ue: int):
        self.shadow = self._draw(n_ue)

    def update_shadow(self, moved_m: np.ndarray):
        idx = np.where(moved_m > 0)[0]
        if len(idx) == 0:
            return idx
        rho = np.exp(-moved_m[idx] / SHADOW_DECORR_M)[:, None]
        self.shadow[idx] = rho * self.shadow[idx] + np.sqrt(1 - rho ** 2) * self._draw(len(idx))
        return idx

    def rsrp(self, ue_xy: np.ndarray, rows: np.ndarray | None = None) -> np.ndarray:
        """Received power (dBm, full band) UE x cell. With ``rows``, only those UEs are recomputed
        (the others have neither moved nor changed shadowing) and the cached matrix is returned."""
        if rows is None or getattr(self, "_rsrp", None) is None:
            rows = np.arange(len(ue_xy))
            self._rsrp = np.empty((len(ue_xy), self.n_cells), dtype=np.float64)
        if len(rows):
            xy = ue_xy[rows]
            dx = xy[:, None, 0] - self.site_xy[None, :, 0]
            dy = xy[:, None, 1] - self.site_xy[None, :, 1]
            d = np.hypot(dx, dy)                                   # UE x site
            ang = np.arctan2(dy, dx)                               # angle from site to UE
            pl = pathloss_db(d) + self.shadow[rows]                # UE x site
            g = sector_gain_db(ang[:, self.cell_site] - self.cell_az[None, :])
            self._rsrp[rows] = TX_DBM + ANT_GAIN_DBI + g - pl[:, self.cell_site]
        return self._rsrp

    @staticmethod
    def sinr(rx_dbm: np.ndarray, serving: np.ndarray, cell_load: np.ndarray, cell_on: np.ndarray) -> np.ndarray:
        """SINR (dB) of each UE on its serving cell; interferers weighted by their load."""
        p = 10 ** (rx_dbm / 10.0)
        w = np.maximum(cell_load, 0.08) * cell_on              # reference signals keep a floor
        n = len(serving)
        idx = np.arange(n)
        s = np.where(serving >= 0, p[idx, np.maximum(serving, 0)], 0.0)
        tot = p @ w
        own = np.where(serving >= 0, s * w[np.maximum(serving, 0)], 0.0)
        interf = tot - own
        noise = 10 ** (NOISE_DBM / 10.0)
        with np.errstate(divide="ignore"):
            return 10 * np.log10(np.maximum(s, 1e-30) / (interf + noise))
