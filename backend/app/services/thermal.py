"""Estimated surface temperature: a small 1-D thermal model.

This is an ESTIMATE, not a measurement. For one place and one season
(solar longitude Ls) it solves the heat equation in the ground through
one Mars sol, repeated until the cycle is periodic, with the classic
surface energy balance used by Mars thermal models (e.g. KRC, Kieffer
2013, JGR Planets 118, 451-470), in a deliberately simplified form:

    (1 - A) * F_sun(t) + L_atm  =  e * sigma * T_s^4  +  k * dT/dz|_0

* F_sun: top-of-atmosphere sunlight for the latitude, Ls and hour
  (Mars orbit: a = 1.5237 AU, e = 0.0934, perihelion at Ls 250.87°,
  obliquity 25.19°), attenuated by dust: direct beam exp(-tau'/mu)
  plus 75 % of the scattered light (dust single-scattering albedo ~0.9,
  strongly forward scattering).
  tau' = tau * P / 610 Pa (thinner dust column on high ground).
* L_atm: downwelling infrared from the dusty CO2 atmosphere, taken as
  a fraction of the noon insolation (2 % + 2 % x tau'), constant over
  the sol: a common simplification.
* Ground: thermal inertia I = sqrt(k rho c) from TES; rho c = 1.2e6
  J m-3 K-1, so k = I^2 / (rho c). 1-D implicit finite differences,
  layers down to ~8 diurnal skin depths, zero flux at the bottom.
* CO2 frost: the surface cannot cool below the CO2 frost point at the
  local pressure (James et al. 1992), ~148 K at 610 Pa.

Not modelled: slopes and shadows, seasonal heat storage (deep annual
wave), clouds, local dust storms, atmospheric temperature coupling,
water ice. Typical error: +-10-20 K for the daily max/min on flat,
dust-free days. Compare: Curiosity/REMS ground temperatures at Gale
reach ~270-295 K by day and ~180-200 K at night depending on season.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

SIGMA = 5.670374419e-8
S0 = 1361.0  # W m-2 at 1 AU
A_AU = 1.52366
ECC = 0.0934
LS_PERIHELION = 250.87
OBLIQUITY = 25.19
SOL_S = 88775.244
RHO_C = 1.2e6
EMISSIVITY = 0.98
P_REF = 610.0
STEPS = 96  # per sol (15 min)
# Share of the light scattered out of the direct beam that still reaches
# the ground: dust single-scattering albedo ~0.9 times the forward-
# scattering share (1 + g) / 2 with asymmetry g ~ 0.65 (Wolff et al.).
DIFFUSE_FRACTION = 0.75
SPINUP_SOLS = 12


@dataclass(frozen=True)
class ThermalResult:
    t_max: float
    t_min: float
    t_mean: float
    hourly: list[tuple[float, float]]  # (local true solar hour, K)
    frost_point: float
    insolation_noon: float  # W m-2 reaching the surface at noon
    sun_up_hours: float

    def at_hour(self, hour: float) -> float:
        hs = np.array([h for h, _ in self.hourly] + [24.0])
        ts = np.array([t for _, t in self.hourly] + [self.hourly[0][1]])
        return float(np.interp(hour % 24.0, hs, ts))


def co2_frost_point(p_pa: float) -> float:
    """CO2 frost point (K) at pressure p (James et al. 1992, P in mbar)."""
    return 3182.48 / (23.3494 - math.log(max(p_pa, 1.0) / 100.0))


def sun_distance_au(ls: float) -> float:
    nu = math.radians(ls - LS_PERIHELION)
    return A_AU * (1 - ECC**2) / (1 + ECC * math.cos(nu))


def solar_declination(ls: float) -> float:
    return math.asin(math.sin(math.radians(OBLIQUITY)) * math.sin(math.radians(ls)))


def _thomas(a, b, c, d):
    """Tridiagonal solver (a: sub, b: diag, c: super)."""
    n = len(d)
    cp = np.empty(n)
    dp = np.empty(n)
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m if i < n - 1 else 0.0
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = np.empty(n)
    x[-1] = dp[-1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


@lru_cache(maxsize=512)
def surface_temperature(lat: float, ls: float, albedo: float, inertia: float,
                        pressure_pa: float, tau: float = 0.5) -> ThermalResult:
    """Diurnal surface temperature cycle (see module docstring)."""
    phi = math.radians(lat)
    dec = solar_declination(ls)
    s_top = S0 / sun_distance_au(ls) ** 2
    tau_eff = tau * pressure_pa / P_REF

    hours = (np.arange(STEPS) + 0.5) * 24.0 / STEPS
    h_angle = np.radians((hours - 12.0) * 15.0)
    mu = np.sin(phi) * math.sin(dec) + np.cos(phi) * math.cos(dec) * np.cos(h_angle)
    mu = np.clip(mu, 0.0, None)
    direct = np.exp(-tau_eff / np.maximum(mu, 0.04))
    f_surf = s_top * mu * (direct + DIFFUSE_FRACTION * (1.0 - direct))
    f_surf[mu <= 0] = 0.0
    mu_noon = max(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec), 0.0)
    l_atm = (0.02 + 0.02 * tau_eff) * s_top * mu_noon
    absorbed = (1.0 - albedo) * f_surf

    # Ground grid
    k = inertia**2 / RHO_C
    kappa = k / RHO_C
    skin = math.sqrt(kappa * SOL_S / math.pi)
    dz = [0.05 * skin]
    while sum(dz) < 8 * skin:
        dz.append(dz[-1] * 1.15)
    dz = np.array(dz)
    n = len(dz)
    dt = SOL_S / STEPS
    t_frost = co2_frost_point(pressure_pa)

    # Start from radiative equilibrium with the sol-mean energy input.
    t_eq = ((absorbed.mean() + l_atm) / (EMISSIVITY * SIGMA)) ** 0.25
    temp = np.full(n, max(t_eq, t_frost))

    # Conductances between layer centres
    zc = np.cumsum(dz) - dz / 2
    g = k / np.diff(zc)  # W m-2 K-1 between i and i+1
    cap = RHO_C * dz / dt  # heat capacity per area per step
    g0 = k / zc[0]  # surface node -> first layer

    # Unknowns per step: [T_surface, T_layer1 .. T_layerN]. The surface
    # node has no heat capacity; its radiation term is linearised around
    # the latest estimate (Newton) and solved TOGETHER with the ground
    # (fully implicit), which keeps the diurnal amplitude independent of
    # the time step.
    m = n + 1
    a = np.zeros(m)
    b = np.zeros(m)
    c = np.zeros(m)
    b[1:] = cap
    b[1] += g0
    a[1] = -g0
    c[0] = -g0
    for i in range(n - 1):
        b[i + 1] += g[i]
        b[i + 2] += g[i]
        c[i + 1] = -g[i]
        a[i + 2] = -g[i]
    ts = float(temp[0])
    record = np.empty(STEPS)
    for sol in range(SPINUP_SOLS + 1):
        for s in range(STEPS):
            d = np.empty(m)
            d[1:] = cap * temp
            for _ in range(2):
                r3 = EMISSIVITY * SIGMA * ts**3
                b[0] = 4 * r3 + g0
                d[0] = absorbed[s] + l_atm + 3 * r3 * ts
                x = _thomas(a, b, c, d)
                ts = float(x[0])
            if ts < t_frost:  # CO2 frost buffers the surface temperature
                ts = t_frost
                x[0] = ts
            temp = x[1:]
            if sol == SPINUP_SOLS:
                record[s] = ts

    hourly = []
    for h in range(24):
        hourly.append((float(h), float(np.interp(h, hours, record, period=24.0))))
    return ThermalResult(
        t_max=float(record.max()),
        t_min=float(record.min()),
        t_mean=float(record.mean()),
        hourly=hourly,
        frost_point=t_frost,
        insolation_noon=float(f_surf.max()),
        sun_up_hours=float((mu > 0).sum() * 24.0 / STEPS),
    )
