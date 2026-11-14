"""Mars calendar: solar longitude (Ls), Mars Year and local solar time.

Algorithm: Allison & McEwen (2000), "A post-Pathfinder evaluation of
areocentric solar coordinates", Planet. Space Sci. 48, 215-235, as used
by NASA GISS Mars24 (https://www.giss.nasa.gov/tools/mars24/help/algorithm.html).
Accuracy is far better than needed here (~0.01° in Ls).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

TT_MINUS_UTC_S = 69.184  # 37 leap seconds + 32.184 s (valid since 2017)

_PBS = [  # perturbations by other planets: (A, tau, phi)
    (0.0071, 2.2353, 49.409),
    (0.0057, 2.7543, 168.173),
    (0.0039, 1.1177, 191.837),
    (0.0037, 15.7866, 21.736),
    (0.0021, 2.1354, 15.704),
    (0.0020, 2.4694, 95.528),
    (0.0018, 32.8493, 49.095),
]


@dataclass(frozen=True)
class MarsTime:
    ls: float  # degrees, 0 = northern spring equinox
    mars_year: int  # Clancy et al. 2000 / Piqueux et al. 2015 numbering (MY 1 = 1955)
    mtc_hours: float  # Coordinated Mars Time (mean solar time at 0° E)
    eot_deg: float  # equation of time (true - mean solar time), degrees


def _sin(d: float) -> float:
    return math.sin(math.radians(d))


def mars_time(when: datetime | None = None) -> MarsTime:
    when = when or datetime.now(timezone.utc)
    jd_ut = when.timestamp() / 86400.0 + 2440587.5
    jd_tt = jd_ut + TT_MINUS_UTC_S / 86400.0
    dt = jd_tt - 2451545.0
    m = 19.3871 + 0.52402073 * dt
    alpha_fms = 270.3871 + 0.524038496 * dt
    pbs = sum(a * math.cos(math.radians(0.985626 * dt / tau + phi)) for a, tau, phi in _PBS)
    nu_m = ((10.691 + 3.0e-7 * dt) * _sin(m) + 0.623 * _sin(2 * m) + 0.050 * _sin(3 * m)
            + 0.005 * _sin(4 * m) + 0.0005 * _sin(5 * m) + pbs)
    ls = (alpha_fms + nu_m) % 360.0
    eot = 2.861 * _sin(2 * ls) - 0.071 * _sin(4 * ls) + 0.002 * _sin(6 * ls) - nu_m
    msd = (jd_tt - 2405522.0028779) / 1.0274912517
    mtc = (24.0 * msd) % 24.0
    # Mars Year: MY 1 started on 1955-04-11 (JD 2435208.5) at Ls = 0.
    # Elapsed years minus the fraction already covered by Ls, rounded,
    # is robust to the non-uniform speed of Ls along the orbit.
    my = round((jd_ut - 2435208.5) / 686.9726 - ls / 360.0) + 1
    return MarsTime(ls=ls, mars_year=int(my), mtc_hours=mtc, eot_deg=eot)


def local_true_solar_hours(t: MarsTime, lon_east: float) -> float:
    """Local true solar time (0-24 h) at an east longitude: 12 h = Sun highest."""
    lmst = (t.mtc_hours + lon_east / 15.0) % 24.0
    return (lmst + t.eot_deg / 15.0) % 24.0


def season_name(ls: float, lat: float) -> str:
    north = ["spring", "summer", "autumn", "winter"][int(ls // 90) % 4]
    south = ["autumn", "winter", "spring", "summer"][int(ls // 90) % 4]
    return f"{'northern' if lat >= 0 else 'southern'} {north if lat >= 0 else south}"


def hhmm(hours: float) -> str:
    h = int(hours) % 24
    m = int(round((hours - int(hours)) * 60)) % 60
    return f"{h:02d}:{m:02d}"
