"""Atmosphere and radiation estimates from elevation (all ESTIMATES).

Surface pressure
    P = P0 * exp(-h / H), P0 = 610 Pa at the MOLA areoid (h = 0), scale
    height H = 11.1 km (Mars Fact Sheet, NASA GSFC). Annual mean: the CO2
    seasonal cycle changes it by about +-10-15 % (Viking/Curiosity), and
    weather adds a few %. Gives ~1,160 Pa on the floor of Hellas and
    ~90 Pa on Olympus Mons (published: ~1,150 and ~70-100 Pa).

Radiation (galactic cosmic rays, surface, quiet Sun)
    Curiosity/RAD measured an average dose equivalent of 0.67 mSv/day on
    the floor of Gale crater (Hassler et al. 2014, Science 343,
    doi:10.1126/science.1244797), under ~20-25 g/cm2 of atmosphere. In
    cruise RAD measured 1.84 mSv/day (Zeitlin et al. 2013, Science 340,
    doi:10.1126/science.1235989); on the surface the planet blocks half
    the sky, so ~0.92 mSv/day is taken as the dose with no atmosphere.
    Between these two anchors we assume exponential attenuation with the
    atmospheric column x = P / g (g = 3.71 m/s2):
        D(x) = D0 * exp(-x / L),  D0 = 0.92 mSv/day,
        L chosen so that D(x_Gale) = 0.67 mSv/day, with x_Gale computed
        from the same pressure model at the Curiosity landing elevation.
    Crude: secondary particles make the real depth dependence flatter or
    even non-monotonic; the solar cycle changes GCR dose by +-30 %; solar
    particle events and local shielding (overhangs, caves, regolith) are
    not included. Uncertainty: at least +-50 %.

Liquid water
    Boiling point of water at the local pressure from the
    Clausius-Clapeyron relation anchored at the triple point
    (611.657 Pa, 273.16 K). Below 611.657 Pa liquid water cannot exist
    in equilibrium: ice sublimates.
"""

from __future__ import annotations

import math

P0_PA = 610.0
SCALE_HEIGHT_M = 11_100.0
G_MARS = 3.71
CURIOSITY_ELEVATION_M = -4501.0  # MOLA, Bradbury Landing
RAD_GALE_MSV_DAY = 0.67
RAD_TOP_MSV_DAY = 1.84 / 2
NASA_CAREER_LIMIT_MSV = 600.0  # NASA-STD-3001 (2022), all astronauts
TRIPLE_P = 611.657
TRIPLE_T = 273.16
L_VAP = 2.45e6  # J/kg, latent heat of vaporisation near 0-10 °C
R_V = 461.5


def surface_pressure_pa(elevation_m: float) -> float:
    return P0_PA * math.exp(-elevation_m / SCALE_HEIGHT_M)


def column_mass_g_cm2(pressure_pa: float) -> float:
    return pressure_pa / G_MARS / 10.0  # kg/m2 -> g/cm2


_X_GALE = column_mass_g_cm2(surface_pressure_pa(CURIOSITY_ELEVATION_M))
ATTENUATION_G_CM2 = _X_GALE / math.log(RAD_TOP_MSV_DAY / RAD_GALE_MSV_DAY)


def gcr_dose_msv_day(pressure_pa: float) -> float:
    return RAD_TOP_MSV_DAY * math.exp(-column_mass_g_cm2(pressure_pa) / ATTENUATION_G_CM2)


def water_boiling_point_k(pressure_pa: float) -> float | None:
    """None when below the triple point (no stable liquid water)."""
    if pressure_pa <= TRIPLE_P:
        return None
    return 1.0 / (1.0 / TRIPLE_T - math.log(pressure_pa / TRIPLE_P) * R_V / L_VAP)
