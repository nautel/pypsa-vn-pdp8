#!/usr/bin/env python3
"""Step B: capacity-expansion study on the K-region transport model (one target year, 3-hourly, weather 2024).

Scenarios
  pdp8 : capacities fixed to the Decision 768/QD-TTg path (S7, low variant; 2035/2040 interpolated geometrically
         between the 2030 and 2050 targets; explicit 2030-35 statements used where given); transmission = existing
         corridors + Decision 1509 lines (S10, mapped to regions) + HVDC 26 GW. Dispatch only (load shedding at VOLL).
  opt  : same demand, same committed assets (hydro, coal pipeline, domestic gas, imports, biomass, rooftop 2024);
         solar/onshore/offshore wind, LNG-CCGT, OCGT, nuclear (Ninh Thuan, <=6.4 GW), batteries, pumped hydro and
         transmission (AC corridors + HVDC candidates) are optimised; CO2 <= emissions of the pdp8 run (same year).
Costs: workflow/repo_data/costs/costs.csv (each value with source). All money USD (real), discount rate 8 %.
Run: python workflow/scripts/model.py <year> <pdp8|opt>
Outputs: <DATA>/expansion/results/<year>_<scen>.nc and <year>_<scen>_summary.json
"""
import json
import os
import sys
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
from scipy.spatial import Delaunay  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
EXP = DATA / "expansion"
RES = EXP / os.environ.get("RES_SUB", "results")  # v5 runs: RES_SUB=results_v5
TAG = os.environ.get("RUN_TAG", "")  # optional suffix for test runs
P8TAG = os.environ.get("PDP8_TAG", TAG)  # PDP8 run used as reference (CO2 cap, intra-region grid)
DSTEP = int(os.environ.get("DAY_STEP", "1"))  # >1: keep every DSTEP-th day (+ peak day), reweighted; same for both scenarios
RES.mkdir(exist_ok=True)
HERE = Path(__file__).resolve().parent
COSTD = HERE.parent / "repo_data" / "costs"
YEAR, SCEN = int(sys.argv[1]), sys.argv[2]
RESAMPLE = "3h"
R = float(os.environ.get("DISCOUNT", "0.08"))  # real discount rate / WACC (sensitivity DISCOUNT=0.10)
MODEL_V_ = os.environ.get("MODEL_V", "6")  # 6: v5 + monthly hydro budgets central; 4 reproduces v4
V5 = MODEL_V_ in ("5", "6")  # v5 defaults
V6 = MODEL_V_ == "6"
CORRIDOR_DERATE = float(os.environ.get("CORR_DERATE", "0.7"))  # usable share of summed thermal ratings on an inter-region corridor (N-1, loop flows)
# ASSUMPTIONS (typical values): availability = max output share (maintenance/forced outage)
AVAIL = {"coal": 0.85, "gas": 0.85, "LNG": 0.88, "OCGT": 0.90, "nuclear": 0.90, "biomass": 0.60, "oil": 0.80}
# capacity credit at the evening peak for the reserve-margin constraint (applied to BOTH scenarios' check)
CREDIT = {"coal": 0.85, "gas": 0.85, "LNG": 0.88, "OCGT": 0.90, "nuclear": 0.90, "biomass": 0.5, "oil": 0.8,
          "imports": 0.8, "hydro": 0.6, "PHS": 0.9, "battery": 0.7, "onwind": 0.1, "offwind": 0.2, "solar": 0.0,
          "rooftop": 0.0}
RESERVE_MARGIN = float(os.environ.get("RM", "1.10"))  # firm capacity >= 110 % of Pmax (sensitivity RM=1.15/1.20)
# v4: penetration-dependent battery credit (declining ELCC of 4 h storage; Sioshansi et al. 2014,
# Denholm et al. 2020): first 10 % of peak demand at 0.9, next 15 % at 0.7, beyond at 0.4; CREDIT_BATTERY scales the
# tranches relative to the former flat value 0.7 (sensitivity CREDIT_BATTERY=0.5 -> 0.64 / 0.5 / 0.29)
BAT_TRANCHES = [(0.10, 0.9), (0.15, 0.7), (None, 0.4)]
BAT_SCALE = float(os.environ.get("CREDIT_BATTERY", "0.7")) / 0.7
CREDIT["battery"] = 0.0  # batteries enter the reserve margin through the tranches only
NORTH_MARGIN = RESERVE_MARGIN  # regional adequacy: northern firm capacity + import capability >= 110 % of the northern peak
UC = os.environ.get("UC", "1") != "0"  # linearised unit commitment of coal plants (Palmintier & Webster 2016)
COAL_MIN, COAL_SU = 0.4, 100.0  # minimum stable load (p.u. of committed capacity); start-up cost USD/MW (Kumar et al. 2012)
RELEASE = set(x for x in os.environ.get("RELEASE", "").split(",") if x)  # pdp8 only: groups optimised instead of fixed
# (cost decomposition: lng, offwind, nuclear, ac, rest). Remaining PDP8 capacities stay fixed; extendables are added on
# top. "rest" releases the plan's solar, onshore wind, batteries, pumped hydro and flexible (OCGT) capacity (v5, Shapley).
# ---- v5 options ----
# capacity reserve margin: "hourly" = chronological, in every snapshot: derated dispatchable capacity + available VRE +
# scheduled net output of storage, hydro and imports >= RM x load (GenX-style CRM; storage/hydro credit endogenous);
# "static" = v4 credits at the annual peak (battery tranches)
CRM = os.environ.get("CRM", "hourly" if V5 else "static")
OPRES = os.environ.get("OPRES", "1" if V5 else "0") != "0"  # operating reserve + SNSP limit in every snapshot
SNSP_MAX = float(os.environ.get("SNSP_MAX", "0.75"))  # max non-synchronous share of demand (EirGrid 75 %, 2022)
OPRES_UNIT_MW, OPRES_VRE = 1200.0, 0.05
# zero-CO2 bounding runs: adequacy and SNSP requirements apply to served load (load shedding at VOLL relieves them);
# otherwise these runs are infeasible because no fossil synchronous capacity may operate
RELAX_SHED = os.environ.get("RELAX_SHED", "1" if (os.environ.get("CO2_CAP", "none") == "0"
                                                  or os.environ.get("NO_RESERVE", "0") != "0") else "0") != "0"  # upward reserve >= largest unit + 5 % of wind and solar output
STORE_W = V5  # storage state of charge with the true step length (3 h) when days are sampled (v4: 12 h, see below)
PLAN = os.environ.get("PLAN_VARIANT", "low")  # Decision 768 variant for demand AND plan capacities (low / high)
GAS_QC = float(os.environ.get("GAS_QC", "0.35" if V5 and os.environ.get("CO2_CAP", "none") != "0" else "0"))  # min annual CF of domestic gas (take-or-pay
# offtake), both scenarios; v5 default = observed 2024 utilisation of the domestic gas fleet (23.0 TWh / 7.49 GW, Ember)
PLAN_RANGE = os.environ.get("PLAN_RANGE", "0") != "0"  # opt: national capacities within Decision 768 low..high ranges
PATH_FROM = os.environ.get("PATH_FROM", "")  # e.g. 2035_opt_vn5: extendables start from that solved earlier year
MGA = os.environ.get("MGA", "")  # "<group>:<eps>", e.g. offwind:0.05 -> maximise group capacity at cost <= (1+eps) opt
MGA_REF = os.environ.get("MGA_REF", "")  # summary of the optimum (same settings) providing the objective value
CROSSOVER = os.environ.get("CROSSOVER", "0") != "0"
HYDRO_MONTHLY = os.environ.get("HYDRO_MONTHLY", "1" if V6 else "0") != "0"  # hydro dispatch <= monthly inflow per region (no shifting
# of water between months), as the monthly budgets of the 2024 nodal model (see the benchmark of the 30 regions)
LNG_COMMITTED = [("Nhon Trach 3&4", 106.95, 10.72, 1624.0)]  # in operation 2025/26 (S17): fixed in every scenario
# v5: LNG projects with a signed PPA or EPC contract by the cut-off date 30 Jun 2026 (S22): Hiep Phuoc 1 (PPA
# 26 Mar 2026, 1,200 MW, COD Q4 2028), Quang Trach II (EPC 9 Feb 2026, 2 x 806.4 MW, COD 2030)
COMMITTED_EXTRA = [("Hiep Phuoc 1", 106.76, 10.62, 1200.0), ("Quang Trach II", 106.43, 17.87, 1612.8)]
if os.environ.get("COMMITTED", "2026" if V5 else "2025") == "2026":
    LNG_COMMITTED = LNG_COMMITTED + COMMITTED_EXTRA
PHS_MAX_MW = 1e3 * (6.0 + (21.327 - 6.0) * (int(sys.argv[1]) - 2030) / 20)  # S11 upper path, opt only
_Y = int(sys.argv[1])
BUILD = {"solar": 11000.0 * (_Y - 2024), "onwind": 3600.0 * (_Y - 2024),  # MW of NEW capacity, opt only (S16)
         "offwind": 1e3 * (17.032 if _Y <= 2035 else 17.032 * (113.503 / 17.032) ** ((_Y - 2035) / 15))}
LNG_QC = float(os.environ.get("LNG_QC", "0"))  # pdp8 only: min annual CF of PDP8 LNG plants (take-or-pay sensitivity).
# Decree 100/2025: Qc >= 65 % of multi-year average output, <= 10 yr, LNG CODs before 2031 (S17); Nhon Trach 3&4
# ~9 TWh/yr on 1,624 MW -> CF 0.63 -> Qc ~ CF 0.41. Default 0 = pure economic dispatch.
IMPORT_CF = (0.45, 0.55)  # annual energy band for Laos/China imports (mostly Lao hydro, take-or-pay PPAs).
# 2024: Ember net imports 5.1 TWh / EVN 1,222 MW = CF 0.48 (D-08, S2). Hourly 0..1 (seasonal hydro shape left to the
# optimiser); an hourly minimum instead of the annual band would let imports run far above their observed use.

# ---------------- PDP8 (Decision 768) path, low variant, GW ----------------
P768_LOW = {  # (2030, 2050), Decision 768 lower bounds (S7)
    "onwind": (26.066, 84.696), "solar_total": (46.459, 293.088), "battery": (10.0, 95.983), "PHS": (2.4, 20.691),
    "flexible": (2.0, 21.333), "imports": (9.36, 14.688), "biomass": (2.964, 6.613), "hydro": (33.294, 40.624),
    "offwind": (6.0, 113.503), "nuclear": (4.0, 10.5), "gas_domestic": 10.861}  # offwind/nuclear: (2035, 2050)
P768_HIGH = {  # upper bounds (S7)
    "onwind": (38.029, 91.4), "solar_total": (73.416, 295.646), "battery": (16.3, 96.12), "PHS": (6.0, 21.327),
    "flexible": (3.0, 38.641), "imports": (12.1, 14.688), "biomass": (4.836, 9.097), "hydro": (34.667, 40.624),
    "offwind": (17.032, 139.097), "nuclear": (6.4, 14.0), "gas_domestic": 14.930}
DEMAND_LOW = {"energy_TWh": (560.4, 1360.1), "pmax_GW": (89.655, 205.732)}  # production+imports, Pmax (base)
DEMAND_HIGH = {"energy_TWh": (624.6, 1511.1), "pmax_GW": (99.934, 228.570)}  # high-demand scenario
P768 = P768_HIGH if PLAN == "high" else P768_LOW
DEMAND = DEMAND_HIGH if PLAN == "high" else DEMAND_LOW
if not V5:  # v4: low variant but offshore wind at the upper bound of the 2030-35 range (17 GW)
    P768 = dict(P768_LOW, offwind=(17.032, 113.503))


def geo(a, b, y):
    return a * (b / a) ** ((y - 2030) / 20)


def pdp8_caps(y, P=None):
    P = P or P768
    c = {k: geo(*v, y) for k, v in P.items() if k not in ["hydro", "offwind", "nuclear", "gas_domestic"]}
    c["hydro"] = P["hydro"][0] + (P["hydro"][1] - P["hydro"][0]) * (y - 2030) / 20  # linear
    o35, o50 = P["offwind"]  # 6-17 GW in operation 2030-35, 113.5-139.1 GW by 2050
    c["offwind"] = o35 if y <= 2035 else geo(o35, o50, 2030 + (y - 2035) * 20 / 15)
    n35, n50 = P["nuclear"]  # NT1&2 4.0-6.4 GW 2030-35; 10.5-14 GW by 2050
    c["nuclear"] = n35 if y <= 2035 else n35 + (n50 - n35) * (y - 2035) / 15
    c["coal"] = 31.055  # pipeline only, conversion after 2035 not modelled
    c["gas_domestic"] = P["gas_domestic"]
    c["LNG"] = 22.524 + 3.0  # + Long Son, Long An II (2031-35)
    return c


# ---------------- costs ----------------
COSTS = os.environ.get("COSTS", "vntc")  # vntc: costs_<year>.csv (VN Technology Catalogue 2026); base: costs.csv (AEO8/tech-data)
CFILE = COSTD / (f"costs_{YEAR}.csv" if COSTS == "vntc" and (COSTD / f"costs_{YEAR}.csv").exists() else "costs.csv")
BENCH = YEAR == 2024  # v5 benchmarking of the 30-region model: 2024 fleet and demand, dispatch only
if BENCH:
    CFILE = COSTD / "costs_2035.csv"  # fuel prices of the 2025 price frameworks; capital costs irrelevant
C = pd.read_csv(CFILE).set_index("tech")
print("costs:", CFILE.name)
# ---- sensitivity overrides (env; default = base case) ----
SENS = {}
if os.environ.get("LNG_USD_MMBTU"):  # delivered LNG price (HHV) -> CCGT/OCGT fuel USD/MWh_th LHV (x3.412 x1.108)
    SENS["LNG_USD_MMBTU"] = float(os.environ["LNG_USD_MMBTU"])
    C.loc[["CCGT", "OCGT"], "fuel_usd_mwhth"] = SENS["LNG_USD_MMBTU"] * 3.412 * 1.108
if os.environ.get("HYDRO_TWH"):  # annual hydro inflow energy (base 100 TWh; dry year e.g. 80)
    SENS["HYDRO_TWH"] = float(os.environ["HYDRO_TWH"])
    C.loc["hydro_energy", "vom_usd_mwh"] = SENS["HYDRO_TWH"]
if os.environ.get("CREDIT_BATTERY"):  # capacity credit of 4 h batteries in the reserve margin (base 0.7)
    SENS["CREDIT_BATTERY"] = float(os.environ["CREDIT_BATTERY"])
if os.environ.get("BAT_CAPEX_X"):  # battery investment cost multiplier
    SENS["BAT_CAPEX_X"] = float(os.environ["BAT_CAPEX_X"])
    C.loc["battery_4h", "capex_usd_kw"] *= SENS["BAT_CAPEX_X"]
if os.environ.get("OFFWIND_CAPEX_X"):  # offshore wind investment cost multiplier
    SENS["OFFWIND_CAPEX_X"] = float(os.environ["OFFWIND_CAPEX_X"])
    C.loc["offwind", "capex_usd_kw"] *= SENS["OFFWIND_CAPEX_X"]
if os.environ.get("BUILD_SOLAR_GW"):  # utility PV build rate GW/yr (base 11 = national PV record 2020 incl. rooftop)
    SENS["BUILD_SOLAR_GW"] = float(os.environ["BUILD_SOLAR_GW"])
    BUILD["solar"] = SENS["BUILD_SOLAR_GW"] * 1e3 * (_Y - 2024)
if os.environ.get("DISCOUNT"):
    SENS["DISCOUNT"] = R
for k_, tech_ in [("NUC_CAPEX_X", ["nuclear"]), ("PHS_CAPEX_X", ["PHS"])]:  # v5 cost sensitivities
    if os.environ.get(k_):
        SENS[k_] = float(os.environ[k_])
        C.loc[tech_, "capex_usd_kw"] *= SENS[k_]
for k_, tech_ in [("SOLAR_CAPEX_X", ["solar"]), ("ONWIND_CAPEX_X", ["onwind"])]:  # v5 Monte Carlo (LHS) factors
    if os.environ.get(k_):
        SENS[k_] = float(os.environ[k_])
        C.loc[tech_, "capex_usd_kw"] *= SENS[k_]
if os.environ.get("COAL_PRICE_X"):  # v6 regret: coal price shock (both coal types)
    SENS["COAL_PRICE_X"] = float(os.environ["COAL_PRICE_X"])
    C.loc[["coal_existing", "coal_new"], "fuel_usd_mwhth"] *= SENS["COAL_PRICE_X"]
if os.environ.get("LINE_CAPEX_X"):  # AC line cost multiplier (circuit 3 north-south: ~2x the catalogue value, S25)
    SENS["LINE_CAPEX_X"] = float(os.environ["LINE_CAPEX_X"])
    C.loc["HVAC_line", "capex_usd_kw"] *= SENS["LINE_CAPEX_X"]
if os.environ.get("CONN_COST"):  # grid-connection adder for utility PV and onshore wind, USD/kW (both scenarios)
    SENS["CONN_COST"] = float(os.environ["CONN_COST"])
    C.loc[["solar", "onwind"], "capex_usd_kw"] += SENS["CONN_COST"]
BAT_BUILD = float(os.environ.get("BAT_BUILD_GW", "0"))  # battery build-rate limit GW/yr (0 = none)
if BAT_BUILD:
    SENS["BAT_BUILD_GW"] = BAT_BUILD
for k_ in ["RM", "CORR_DERATE", "GAS_QC", "PLAN_VARIANT", "PLAN_RANGE", "PATH_FROM", "MGA", "CRM", "OPRES", "SNSP_MAX",
           "COMMITTED", "MODEL_V", "HYDRO_MONTHLY", "COAL_PRICE_X", "BAT_NEW_X", "NORTH_CORR_X", "WEATHER_YEAR", "FIX_FROM", "OUTAGE_SEED", "DEMAND_X", "SOLAR_NEW_X", "NO_RESERVE"]:
    if os.environ.get(k_):
        SENS[k_] = os.environ[k_]
if os.environ.get("CREDIT_BATTERY"):
    SENS["CREDIT_BATTERY_SCALE"] = BAT_SCALE
if RELEASE:
    SENS["RELEASE"] = sorted(RELEASE)
BUILD_LIMIT = os.environ.get("BUILD_LIMIT", "1") != "0"  # 0 = drop solar/onwind/offwind build-rate caps (opt)
if not BUILD_LIMIT:
    SENS["BUILD_LIMIT"] = 0
print("sensitivity overrides:", SENS or "none")
EFF_BAT = C.loc["battery_4h", "eff"] if C.loc["battery_4h", "eff"] > 0 else 0.92
EFF_PHS = C.loc["PHS", "eff"] if C.loc["PHS", "eff"] > 0 else 0.87
H_PHS = C.loc["PHS_max_hours", "vom_usd_mwh"] if "PHS_max_hours" in C.index else 8


def annuity(life):
    return R / (1 - (1 + R) ** -life)


def capcost(t):  # USD/MW/yr (annualised capex + FOM)
    r = C.loc[t]
    return r.capex_usd_kw * 1e3 * (annuity(r.life) + r.fom_pct / 100)


def mc(t):
    r = C.loc[t]
    return (r.fuel_usd_mwhth / r.eff if r.eff > 0 else 0) + r.vom_usd_mwh


# ---------------- data ----------------
cl = pd.read_csv(EXP / "clusters.csv", index_col=0)
busmap = pd.read_csv(EXP / "busmap.csv", index_col=0).cluster
cor = pd.read_csv(EXP / "corridors.csv", index_col=0)
calib = json.loads((EXP / "cf_calibration.json").read_text())
cf = {k: pd.read_csv(EXP / f"cf_{k}.csv", index_col=0, parse_dates=True) for k in ["solar", "rooftop", "onwind", "offwind"]}
cf["solar"] *= calib["factor_solar"]
cf["rooftop"] *= calib["factor_solar"]
cf["onwind"] = (cf["onwind"] * calib["factor_wind"]).clip(upper=1)
if (EXP / "cf_onwind_new.csv").exists():  # new 2030s turbines, ERA5 speed bias-corrected (onwind_new_cf.py)
    cf["onwind_new"] = pd.read_csv(EXP / "cf_onwind_new.csv", index_col=0, parse_dates=True)
else:
    cf["onwind_new"] = cf["onwind"]
# VRE_SRC=gis (default, v3): eligible-area-weighted ERA5 x Global Wind Atlas profiles and land-eligibility potentials
# (vre_gis.py, D-21..D-24); existing plants use their own sites; onshore wind split into resource classes w1-w3.
# VRE_SRC=point (v2): one ERA5 point per region (prepare.py / onwind_new_cf.py), potentials split by region area.
VRE_SRC = os.environ.get("VRE_SRC", "gis")
GISD = EXP / "gis"
WCLS = []
if VRE_SRC == "gis":
    rd = lambda k: pd.read_csv(GISD / f"cf_{k}.csv", index_col=0, parse_dates=True).reindex(columns=cl.index)  # noqa: E731
    cf["solar"], cf["solar_exist"], cf["onwind"] = rd("solar"), rd("solar_exist"), rd("onwind")
    WCLS = sorted(p_.stem.split("_")[-1] for p_ in GISD.glob("cf_onwind_new_w*.csv"))
    for w_ in WCLS:
        cf[f"onwind_new_{w_}"] = rd(f"onwind_new_{w_}")
    potg = pd.read_csv(GISD / "potentials.csv", index_col=0).reindex(cl.index).fillna(0)
    cf["onwind_new"] = cf[f"onwind_new_{WCLS[0]}"]  # placeholder; PDP8 additions use best-first class mix (below)
else:
    cf["solar_exist"] = cf["solar"]
for k in cf:  # numerics: drop tiny CF coefficients
    cf[k] = cf[k].clip(upper=1).where(cf[k] >= 1e-3, 0.0)
WY = os.environ.get("WEATHER_YEAR", "")  # v5 adequacy/regret: ERA5 weather year (weather_years.py, D-25)
if WY and WY != "2024":
    for k_ in list(cf):
        f_ = EXP / "weather_years" / f"cf_{k_}_{WY}.csv"
        if f_.exists():
            cf[k_] = pd.read_csv(f_, index_col=0, parse_dates=True).reindex(columns=cf[k_].columns).fillna(0.0)
            cf[k_] = cf[k_].where(cf[k_] >= 1e-3, 0.0)
    if WCLS:
        cf["onwind_new"] = cf[f"onwind_new_{WCLS[0]}"]
    print("weather year", WY)
base = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
g0 = base.generators[base.generators.carrier != "load shedding"].assign(cl=lambda d: d.bus.map(busmap))
s0 = base.storage_units.assign(cl=lambda d: d.bus.map(busmap))
cap24 = g0.groupby(["cl", "carrier"]).p_nom.sum().unstack(fill_value=0).reindex(cl.index, fill_value=0)
hyd24 = s0.groupby("cl").p_nom.sum().reindex(cl.index, fill_value=0)

# demand: 2024 shape and spatial split, scaled to target energy and Pmax (affine stretch keeps energy)
lt = base.loads_t.p_set.T.groupby(base.loads.bus.map(busmap)).sum().T.reindex(columns=cl.index, fill_value=0)
nat = lt.sum(axis=1)
E_t, P_t = geo(*DEMAND["energy_TWh"], YEAR) * 1e6, geo(*DEMAND["pmax_GW"], YEAR) * 1e3
if BENCH:  # observed 2024 demand (nodal model, Ember/EVN totals)
    E_t, P_t = float(nat.sum()), float(nat.max())
nat2 = nat * E_t / nat.sum()
m = nat2.mean()
k = (P_t - m) / (nat2.max() - m)
nat2 = m + (nat2 - m) * k
load = lt.div(nat, axis=0).mul(nat2, axis=0)

# optional extra loads on top of the Decision-768 forecast (which does not mention data centres or HSR):
# EXTRA=dc  -> data centres: ~1 GW by 2030 (market outlooks) x 12.6 %/yr trend + 1-2 hyperscale AI campuses
#              = 3 GW (2035) / 5 GW (2040) facility power, flat at 80 % utilisation (ASSUMPTIONS, docs/data_sources.md sec. 6)
# EXTRA=hsr -> North-South high-speed rail (Resolution 172/2024/QH15, 1,541 km, 350 km/h): peak 350 MW (2035,
#              initial service) / 900 MW (2040), 20 feeding points, service 6-23 h, peaks 7-9 h and 17-20 h (ASSUMPTIONS)
EXTRA = os.environ.get("EXTRA", "")  # "", "dc", "hsr" or combined "dc+hsr"
PARTS = [x for x in EXTRA.replace(",", "+").split("+") if x]
_near = lambda lon, lat: cl.index[np.argmin(np.hypot(cl.x - lon, cl.y - lat))]  # noqa: E731
extra = pd.DataFrame(0.0, index=load.index, columns=load.columns)
if "dc" in PARTS:
    DC_MW, DC_UTIL = {2035: 3000, 2040: 5000}[YEAR], 0.8
    for (lon, lat), sh in {(105.53, 21.01): 0.25, (105.98, 21.20): 0.15, (108.15, 16.07): 0.10,
                           (106.79, 10.84): 0.50}.items():  # Hoa Lac, Yen Phong, Da Nang, Thu Duc
        extra[_near(lon, lat)] += DC_MW * DC_UTIL * sh
if "hsr" in PARTS:
    HSR_MW = {2035: 350, 2040: 900}[YEAR]
    HSR_PTS = [(105.84, 20.92), (105.92, 20.54), (106.17, 20.42), (105.97, 20.25), (105.78, 19.80), (105.68, 18.68),
               (105.90, 18.34), (106.60, 17.47), (107.10, 16.82), (107.59, 16.46), (108.20, 16.03), (108.47, 15.57),
               (108.80, 15.12), (109.10, 13.95), (109.30, 13.09), (109.15, 12.25), (108.99, 11.57), (108.10, 10.93),
               (107.00, 10.78), (106.72, 10.78)]
    hh = load.index.hour
    shape = np.where((hh >= 6) & (hh <= 23), 0.6, 0.0)
    shape[np.isin(hh, [7, 8, 17, 18, 19])] = 1.0
    for lon, lat in HSR_PTS:
        extra[_near(lon, lat)] += shape * HSR_MW / len(HSR_PTS)
if set(PARTS) - {"dc", "hsr"}:
    raise SystemExit(f"unknown EXTRA={EXTRA}")
DX = float(os.environ.get("DEMAND_X", "1"))  # v5 regret: demand scaling of a fixed portfolio
if DX != 1:
    load, E_t, P_t = load * DX, E_t * DX, P_t * DX
P_base = P_t
if EXTRA:
    load = load + extra
    E_t = E_t + float(extra.values.sum())
    P_t = float(load.sum(axis=1).max())
    print(f"EXTRA={EXTRA}: +{extra.values.sum() / 1e6:.2f} TWh, peak +{extra.sum(axis=1).max():.0f} MW, "
          f"system Pmax {P_base / 1e3:.1f} -> {P_t / 1e3:.1f} GW; by cluster MW(max): "
          f"{extra.max()[extra.max() > 0].round(0).to_dict()}")

n = pypsa.Network()
snap = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")
n.set_snapshots(snap)
n.add("Bus", cl.index, x=cl.x, y=cl.y, carrier="AC")
carriers = ["coal", "gas", "LNG", "OCGT", "oil", "biomass", "nuclear", "imports", "solar", "rooftop", "onwind",
            "offwind", "hydro", "battery", "PHS", "AC", "DC", "load shedding"]
co2 = {"coal": C.loc["coal_existing", "co2_t_mwhth"], "gas": C.loc["gas_domestic", "co2_t_mwhth"],
       "LNG": C.loc["CCGT", "co2_t_mwhth"], "OCGT": C.loc["OCGT", "co2_t_mwhth"], "oil": C.loc["oil", "co2_t_mwhth"]}
n.add("Carrier", carriers, co2_emissions=[co2.get(c, 0.0) for c in carriers])
n.add("Load", cl.index, suffix=" load", bus=cl.index, p_set=load.values)
n.add("Generator", cl.index, suffix=" load shedding", bus=cl.index, carrier="load shedding", p_nom=1e6,
      marginal_cost=C.loc["VOLL", "vom_usd_mwh"])

caps = pdp8_caps(YEAR)
if BENCH:  # no additions: 2024 fleet only
    caps.update({"coal": cap24["coal"].sum() / 1e3, "gas_domestic": cap24["gas"].sum() / 1e3,
                 "biomass": cap24["biomass"].sum() / 1e3, "hydro": hyd24.sum() / 1e3, "imports": 1.222})
# ---- committed / existing thermal (both scenarios) ----
for (c, t), mw in g0.groupby(["cl", "carrier"]).p_nom.sum().items():
    if t in ["coal", "gas", "oil", "biomass"]:
        tech = {"coal": "coal_existing", "gas": "gas_domestic", "oil": "oil", "biomass": "biomass"}[t]
        n.add("Generator", f"{c} {t} existing", bus=c, carrier=t, p_nom=mw, marginal_cost=mc(tech),
              efficiency=C.loc[tech, "eff"], p_max_pu=AVAIL[t])
gem = pd.read_csv(DATA / "plants" / "vn_units_gem.csv")
gem = gem[gem.lat.notna()]
gx = gpd.GeoSeries(gpd.points_from_xy(gem.lon, gem.lat), crs=4326).to_crs(32648)
cx = gpd.GeoSeries(gpd.points_from_xy(cl.x, cl.y), crs=4326).to_crs(32648)
gem["cl"] = cl.index[np.argmin(np.hypot(gx.x.values[:, None] - cx.x.values[None], gx.y.values[:, None] - cx.y.values[None]), 1)]
pipe = gem[gem.status.isin(["construction", "pre-construction", "pre-permit", "permitted", "announced"]) &
           (gem.start_year.isna() | (gem.start_year <= YEAR))]


def spread(total_mw, carrier_gem, fallback):
    """distribute an increment over regions pro rata to GEM pipeline of that carrier (else to `fallback`)."""
    w = pipe[pipe.carrier.isin(carrier_gem)].groupby("cl").capacity_mw.sum().reindex(cl.index, fill_value=0)
    if w.sum() == 0:
        w = fallback.reindex(cl.index, fill_value=0)
    return (w / w.sum() * max(total_mw, 0)).fillna(0)


coal_add = spread(caps["coal"] * 1e3 - cap24["coal"].sum(), ["coal"], cap24["coal"])
for c, mw in coal_add[coal_add > 1].items():
    n.add("Generator", f"{c} coal committed", bus=c, carrier="coal", p_nom=mw, marginal_cost=mc("coal_new"),
          efficiency=C.loc["coal_new", "eff"], p_max_pu=AVAIL["coal"])
dg_add = pd.Series(0.0, index=cl.index)  # domestic gas: O Mon (Can Tho) + Dung Quat/Mien Trung (Quang Nam-Ngai)
for lon, lat, sh in [(105.70, 10.10, 0.5), (108.75, 15.35, 0.5)]:
    i = np.argmin(np.hypot(cl.x - lon, cl.y - lat))
    dg_add.iloc[i] += sh * (caps["gas_domestic"] * 1e3 - cap24["gas"].sum())
for c, mw in dg_add[dg_add > 1].items():
    n.add("Generator", f"{c} gas committed", bus=c, carrier="gas", p_nom=mw, marginal_cost=mc("gas_domestic"),
          efficiency=C.loc["gas_domestic", "eff"], p_max_pu=AVAIL["gas"])
bio = cap24["biomass"] * caps["biomass"] * 1e3 / max(cap24["biomass"].sum(), 1)
for c, mw in (bio - cap24["biomass"]).clip(lower=0).items():
    if mw > 1:
        n.add("Generator", f"{c} biomass committed", bus=c, carrier="biomass", p_nom=mw, marginal_cost=mc("biomass"),
              p_max_pu=AVAIL["biomass"])
HOURS = float(n.snapshot_weightings.generators.sum())  # full-year hours represented
if GAS_QC > 0:  # domestic gas take-or-pay (Block B / Ca Voi Xanh contracts): minimum annual output, both scenarios
    gq = n.generators.index[n.generators.carrier == "gas"]
    n.generators.loc[gq, "e_sum_min"] = GAS_QC * n.generators.p_nom[gq] * HOURS
imp = pd.Series(0.0, index=cl.index)  # Laos/China imports: North (Son La/Nghe An) and Central (Quang Tri/Kon Tum)
for lon, lat, sh in [(104.0, 21.3, 0.3), (105.3, 19.0, 0.3), (106.9, 16.7, 0.2), (107.9, 14.4, 0.2)]:
    imp.iloc[np.argmin(np.hypot(cl.x - lon, cl.y - lat))] += sh * caps["imports"] * 1e3
for c, mw in imp[imp > 0].items():
    n.add("Generator", f"{c} imports", bus=c, carrier="imports", p_nom=mw, marginal_cost=C.loc["imports", "vom_usd_mwh"],
          p_min_pu=0.0, p_max_pu=1.0, e_sum_min=IMPORT_CF[0] * mw * HOURS, e_sum_max=IMPORT_CF[1] * mw * HOURS)
# hydro (reservoir + run-of-river aggregated), scaled to the PDP8 level; inflow energy from assumption table
hyd = hyd24 * caps["hydro"] * 1e3 / hyd24.sum()
infl_base = base.storage_units_t.inflow.T.groupby(s0.cl).sum().T.reindex(columns=cl.index, fill_value=0)
infl = infl_base * C.loc["hydro_energy", "vom_usd_mwh"] * 1e6 / infl_base.sum().sum()
for c in cl.index[hyd > 1]:
    n.add("StorageUnit", f"{c} hydro", bus=c, carrier="hydro", p_nom=hyd[c], max_hours=24 * 31,
          efficiency_store=0, efficiency_dispatch=1, cyclic_state_of_charge=True, inflow=infl[c].values)
# VRE existing + rooftop (both)
for t, k, prof_ in [("solar", "solar", "solar_exist"), ("solar rooftop", "rooftop", "rooftop"), ("onwind", "onwind", "onwind")]:
    for c, mw in cap24[t][cap24[t] > 0].items():
        n.add("Generator", f"{c} {k} existing", bus=c, carrier=k, p_nom=mw, p_max_pu=cf[prof_][c].values,
              marginal_cost=0.0)

# ---------------- region potentials (for extendable VRE) ----------------
g2 = gpd.read_file(DATA / "shapes" / "gadm41_VNM_2.json").to_crs(32648)
rp = g2.geometry.representative_point()
area = pd.Series(g2.geometry.area.values / 1e6, index=cl.index[np.argmin(np.hypot(
    rp.x.values[:, None] - cx.x.values[None], rp.y.values[:, None] - cx.y.values[None]), 1)]).groupby(level=0).sum()
area = area.reindex(cl.index, fill_value=0)
pot = {"solar": area / area.sum() * 837e3, "onwind": area / area.sum() * 221e3}  # MW, Decision 768 national potentials
if VRE_SRC == "gis":  # same national totals, regional split by eligible land; wind per resource class
    pot["solar"] = potg.pot_solar_MW
    for w_ in WCLS:
        pot[f"onwind_{w_}"] = potg[f"pot_onwind_{w_}_MW"]


def onwind_mix(c, mw):
    """PDP8 onshore wind in region c: fill resource classes best-first up to their potentials (developers take the
    best sites first); overflow beyond the regional potential goes to the last class. Returns hourly CF array."""
    if not WCLS:
        return cf["onwind_new"][c].values
    left, prof_ = mw, 0.0
    for i_, w_ in enumerate(WCLS):
        take = left if i_ == len(WCLS) - 1 else min(left, pot[f"onwind_{w_}"][c])
        prof_ = prof_ + take * cf[f"onwind_new_{w_}"][c].values
        left -= take
        if left <= 0:
            break
    return prof_ / mw
coastal = cl.index[cl.offshore_ok]
pot["offwind"] = pd.Series(600e3 / len(coastal), index=coastal)

# ---------------- transmission ----------------
cor["p_nom"] = cor.mw * CORRIDOR_DERATE
tri = Delaunay(np.c_[cl.x, cl.y])
pairs = set()
for s in tri.simplices:
    for i in range(3):
        a, b = sorted([cl.index[s[i]], cl.index[s[(i + 1) % 3]]])
        pairs.add(f"{a}|{b}")
dist = lambda a, b: 1.2 * 111.2 * np.hypot((cl.x[a] - cl.x[b]) * np.cos(np.radians((cl.y[a] + cl.y[b]) / 2)), cl.y[a] - cl.y[b])  # noqa: E731
allp = pd.DataFrame(index=sorted(pairs | set(cor.index)))
allp[["c0", "c1"]] = allp.index.to_series().str.split("|", expand=True).values
allp["km"] = [dist(a, b) for a, b in zip(allp.c0, allp.c1)]
allp = allp[(allp.km < 450) | allp.index.isin(cor.index)]
allp["p_nom"] = cor.p_nom.reindex(allp.index).fillna(0)
HVDC = [("TTB1-BB1", (106.85, 17.15), (106.17, 20.42), 7000), ("TTB2-BB2", (108.80, 15.10), (105.55, 21.00), 7000),
        ("NTB-BB3", (108.95, 11.60), (106.05, 20.85), 6000), ("BRVT-HP", (107.20, 10.50), (106.70, 20.85), 6000)]
near = lambda lon, lat: cl.index[np.argmin(np.hypot(cl.x - lon, cl.y - lat))]  # noqa: E731

if SCEN == "pdp8" and "ac" not in RELEASE and not BENCH:
    # Decision 1509 lines (located, plausible) mapped to region pairs; capacity per circuit, scaled by coverage
    Lp = pd.read_csv(DATA / "plans" / "qd1509_lines_geo.csv")
    Lp = Lp[Lp.period.isin(["2025-2030"] + (["2031-2035"] if YEAR >= 2035 else []))]
    Lp["map_km"] = 111.2 * np.hypot((Lp.x1 - Lp.x0) * np.cos(np.radians((Lp.y0 + Lp.y1) / 2)), Lp.y1 - Lp.y0)
    ok = Lp.ok & (Lp.map_km <= np.maximum(1.6 * Lp.km, Lp.km + 40))
    cov = Lp[ok].groupby("kv").circuit_km.sum() / Lp.groupby("kv").circuit_km.sum()
    Lp = Lp[ok].copy()
    pa = gpd.GeoSeries(gpd.points_from_xy(Lp.x0, Lp.y0), crs=4326).to_crs(32648)
    pb = gpd.GeoSeries(gpd.points_from_xy(Lp.x1, Lp.y1), crs=4326).to_crs(32648)
    Lp["c0"] = cl.index[np.argmin(np.hypot(pa.x.values[:, None] - cx.x.values[None], pa.y.values[:, None] - cx.y.values[None]), 1)]
    Lp["c1"] = cl.index[np.argmin(np.hypot(pb.x.values[:, None] - cx.x.values[None], pb.y.values[:, None] - cx.y.values[None]), 1)]
    Lp = Lp[Lp.c0 != Lp.c1]
    Lp["mw"] = Lp.circuits.fillna(2) * np.where(Lp.kv == 500, C.loc["AC_500_circuit_MW", "vom_usd_mwh"],
                                                C.loc["AC_220_circuit_MW", "vom_usd_mwh"]) * CORRIDOR_DERATE / Lp.kv.map(cov)
    Lp["key"] = np.where(Lp.c0 < Lp.c1, Lp.c0 + "|" + Lp.c1, Lp.c1 + "|" + Lp.c0)
    add = Lp.groupby("key").mw.sum()
    for kk in add.index.difference(allp.index):
        a, b2 = kk.split("|")
        allp.loc[kk, ["c0", "c1", "km", "p_nom"]] = [a, b2, dist(a, b2), 0.0]
    allp["p_nom"] = allp.p_nom + add.reindex(allp.index).fillna(0)
    allp["p_nom_added"] = add.reindex(allp.index).fillna(0)
n.add("Link", "AC " + allp.index, bus0=allp.c0.values, bus1=allp.c1.values, carrier="AC", p_min_pu=-1,
      p_nom=allp.p_nom.values, p_nom_min=allp.p_nom.values, p_nom_extendable=(SCEN == "opt" or "ac" in RELEASE),
      capital_cost=(allp.km * C.loc["HVAC_line", "capex_usd_kw"] / CORRIDOR_DERATE *  # per usable MW (thermal / derate)
                    (annuity(C.loc["HVAC_line", "life"]) + C.loc["HVAC_line", "fom_pct"] / 100)).values,
      length=allp.km.values, efficiency=1.0)
hv_years = YEAR >= 2035
for name, p0, p1, mw in HVDC:
    a, b2 = near(*p0), near(*p1)
    km = dist(a, b2)
    cc = km * C.loc["HVDC_line", "capex_usd_kw"] * (annuity(C.loc["HVDC_line", "life"]) + C.loc["HVDC_line", "fom_pct"] / 100) \
        + capcost("HVDC_converter_pair")
    if SCEN == "pdp8" and "ac" not in RELEASE:
        n.add("Link", f"HVDC {name}", bus0=a, bus1=b2, carrier="DC", p_min_pu=-1, p_nom=mw if hv_years else 0,
              length=km, efficiency=1.0)  # lossless like AC transport links: a lossy p_min_pu=-1 link gains energy in reverse
    else:
        n.add("Link", f"HVDC {name}", bus0=a, bus1=b2, carrier="DC", p_min_pu=-1, p_nom_extendable=True,
              capital_cost=cc, length=km, efficiency=1.0)

# ---------------- new generation & storage ----------------
NT = near(108.98, 11.43)
coastal_lng = cl.index[cl.coast_km < 60]
if SCEN == "pdp8" and not BENCH:
    # spatial split of PDP8 solar/onwind additions: Decision 1509 Annex II.1 project lists by province (ALLOC=qd1509,
    # default; parse_qd1509_sources.py) or the GEM pipeline (ALLOC=gem, earlier runs; put ~10x too much solar in Phu Yen)
    ALLOC = os.environ.get("ALLOC", "qd1509")
    qd_w = pd.read_csv(DATA / "plans" / "qd1509_sources_by_cluster.csv", index_col=0) if ALLOC == "qd1509" else None

    def spread_vre(total_mw, car):
        if qd_w is None:
            return spread(total_mw, [car], cap24[car])
        w_ = qd_w[car].reindex(cl.index, fill_value=0)
        return w_ / w_.sum() * max(total_mw, 0)

    print("PDP8 VRE allocation:", ALLOC)
    adds = {"solar": spread_vre(caps["solar_total"] * 1e3 - cap24["solar"].sum() - cap24["solar rooftop"].sum(), "solar"),
            "onwind": spread_vre(caps["onwind"] * 1e3 - cap24["onwind"].sum(), "onwind"),
            "offwind": spread(caps["offwind"] * 1e3, ["offwind"], pd.Series(1.0, index=coastal)),
            "LNG": spread(caps["LNG"] * 1e3, ["gas"], load.max()),
            "OCGT": load.max() / load.max().sum() * caps["flexible"] * 1e3}
    adds["offwind"] = adds["offwind"].reindex(coastal, fill_value=0)
    adds["offwind"] = adds["offwind"] / adds["offwind"].sum() * caps["offwind"] * 1e3
    for t, ser in adds.items():
        if t.lower() in RELEASE or ("rest" in RELEASE and t in ["solar", "onwind", "OCGT"]):
            continue
        for c, mw in ser[ser > 1].items():
            kw = dict(p_max_pu=onwind_mix(c, mw) if t == "onwind" else cf[t][c].values) if t in ["solar", "onwind", "offwind"] \
                else dict(p_max_pu=AVAIL[t])
            tech = {"solar": "solar", "onwind": "onwind", "offwind": "offwind", "LNG": "CCGT", "OCGT": "OCGT"}[t]
            if t == "LNG" and LNG_QC > 0:  # Decree 100/2025 minimum contracted output (S17), sensitivity only
                kw["e_sum_min"] = LNG_QC * mw * HOURS
            n.add("Generator", f"{c} {t} new", bus=c, carrier=t, p_nom=mw, marginal_cost=mc(tech),
                  efficiency=C.loc[tech, "eff"] if C.loc[tech, "eff"] > 0 else 1, capital_cost=capcost(tech), **kw)
    if "nuclear" not in RELEASE:
        n.add("Generator", f"{NT} nuclear new", bus=NT, carrier="nuclear", p_nom=caps["nuclear"] * 1e3,
              marginal_cost=mc("nuclear"), capital_cost=capcost("nuclear"), p_max_pu=AVAIL["nuclear"])
    if not (RELEASE - {"storage"}):  # equal reliability standard: PDP8 may add OCGT where it misses the margins
        for c in cl.index:
            n.add("Generator", f"{c} OCGT new topup", bus=c, carrier="OCGT", p_nom_extendable=True,
                  capital_cost=capcost("OCGT"), marginal_cost=mc("OCGT"), efficiency=C.loc["OCGT", "eff"],
                  p_max_pu=AVAIL["OCGT"])
    vre = (adds["solar"].reindex(cl.index, fill_value=0) + adds["onwind"].reindex(cl.index, fill_value=0))
    bat = vre / vre.sum() * caps["battery"] * 1e3
    phs = hyd / hyd.sum() * caps["PHS"] * 1e3
    for c in (cl.index if not ({"rest", "storage"} & RELEASE) else []):
        if bat[c] > 1:
            n.add("StorageUnit", f"{c} battery", bus=c, carrier="battery", p_nom=bat[c], max_hours=4,
                  efficiency_store=EFF_BAT, efficiency_dispatch=EFF_BAT, cyclic_state_of_charge=True, capital_cost=capcost("battery_4h"))
        if phs[c] > 1:
            n.add("StorageUnit", f"{c} PHS", bus=c, carrier="PHS", p_nom=phs[c], max_hours=H_PHS, efficiency_store=EFF_PHS,
                  efficiency_dispatch=EFF_PHS, cyclic_state_of_charge=True, capital_cost=capcost("PHS"))
STOR_ONLY = RELEASE == {"storage"}  # v6: the plan's storage totals with optimised siting
if STOR_ONLY:
    for c in cl.index:
        n.add("StorageUnit", f"{c} battery ext", bus=c, carrier="battery", p_nom_extendable=True, max_hours=4,
              efficiency_store=EFF_BAT, efficiency_dispatch=EFF_BAT, cyclic_state_of_charge=True, capital_cost=capcost("battery_4h"))
        if hyd[c] > 500:
            n.add("StorageUnit", f"{c} PHS ext", bus=c, carrier="PHS", p_nom_extendable=True, p_nom_max=3000, max_hours=H_PHS,
                  efficiency_store=EFF_PHS, efficiency_dispatch=EFF_PHS, cyclic_state_of_charge=True, capital_cost=capcost("PHS"))
if SCEN == "opt" or (RELEASE and not STOR_ONLY):
    sfx = " ext" if RELEASE else ""  # avoid name clashes with fixed PDP8 assets in release mode
    fx = n.generators[~n.generators.p_nom_extendable & n.generators.index.str.contains(" new")]
    used = fx.groupby(["carrier", "bus"]).p_nom.sum()  # fixed PDP8 additions consume regional potential
    use = lambda car, c: float(used.get((car, c), 0.0))  # noqa: E731
    if SCEN == "opt" or "lng" in RELEASE:
        for nm_, lon_, lat_, mw_ in LNG_COMMITTED:
            n.add("Generator", f"{near(lon_, lat_)} LNG new committed", bus=near(lon_, lat_), carrier="LNG", p_nom=mw_,
                  capital_cost=capcost("CCGT"), marginal_cost=mc("CCGT"), efficiency=C.loc["CCGT", "eff"],
                  p_max_pu=AVAIL["LNG"])
    for c in cl.index:
        n.add("Generator", f"{c} solar new{sfx}", bus=c, carrier="solar", p_nom_extendable=True,
              p_nom_max=max(pot["solar"][c] - use("solar", c), 0), p_max_pu=cf["solar"][c].values,
              capital_cost=capcost("solar"), marginal_cost=0.01)
        if WCLS:
            left_ = use("onwind", c)  # fixed PDP8 wind occupies the best classes first
            for w_ in WCLS:
                cap_w = pot[f"onwind_{w_}"][c]
                taken = min(left_, cap_w)
                left_ -= taken
                if cap_w - taken > 1:
                    n.add("Generator", f"{c} onwind new {w_}{sfx}", bus=c, carrier="onwind", p_nom_extendable=True,
                          p_nom_max=cap_w - taken, p_max_pu=cf[f"onwind_new_{w_}"][c].values,
                          capital_cost=capcost("onwind"), marginal_cost=0.02)
        else:
            n.add("Generator", f"{c} onwind new{sfx}", bus=c, carrier="onwind", p_nom_extendable=True,
                  p_nom_max=max(pot["onwind"][c] - use("onwind", c), 0), p_max_pu=cf["onwind_new"][c].values,
                  capital_cost=capcost("onwind"), marginal_cost=0.02)
        if c in coastal:
            n.add("Generator", f"{c} offwind new{sfx}", bus=c, carrier="offwind", p_nom_extendable=True,
                  p_nom_max=max(pot["offwind"][c] - use("offwind", c), 0), p_max_pu=cf["offwind"][c].values,
                  capital_cost=capcost("offwind"), marginal_cost=0.02)
        if c in coastal_lng:
            n.add("Generator", f"{c} LNG new{sfx}", bus=c, carrier="LNG", p_nom_extendable=True, capital_cost=capcost("CCGT"),
                  marginal_cost=mc("CCGT"), efficiency=C.loc["CCGT", "eff"], p_max_pu=AVAIL["LNG"], p_nom_max=30000)
        n.add("Generator", f"{c} OCGT new{sfx}", bus=c, carrier="OCGT", p_nom_extendable=True, capital_cost=capcost("OCGT"),
              marginal_cost=mc("OCGT"), efficiency=C.loc["OCGT", "eff"], p_max_pu=AVAIL["OCGT"], p_nom_max=30000)
        n.add("StorageUnit", f"{c} battery{sfx}", bus=c, carrier="battery", p_nom_extendable=True, max_hours=4,
              efficiency_store=EFF_BAT, efficiency_dispatch=EFF_BAT, cyclic_state_of_charge=True, capital_cost=capcost("battery_4h"))
        if hyd[c] > 500:
            n.add("StorageUnit", f"{c} PHS{sfx}", bus=c, carrier="PHS", p_nom_extendable=True, p_nom_max=3000, max_hours=H_PHS,
                  efficiency_store=EFF_PHS, efficiency_dispatch=EFF_PHS, cyclic_state_of_charge=True, capital_cost=capcost("PHS"))
    n.add("Generator", f"{NT} nuclear new{sfx}", bus=NT, carrier="nuclear", p_nom_extendable=True,
          p_nom_max=max(6400 - use("nuclear", NT), 0), marginal_cost=mc("nuclear"), capital_cost=capcost("nuclear"),
          p_max_pu=AVAIL["nuclear"])
CAP = os.environ.get("CO2_CAP", "none")
if SCEN == "opt" or (CAP != "none" and not CAP.startswith("pdp8")):
    # CO2 policy (PyPSA-ZA-style scenario axis). Default "none" = pure economic least cost (CO2 reported only).
    #   CO2_CAP=pdp8      -> emissions <= PDP8 run of the same tag (opt only)
    #   CO2_CAP=pdp8*0.5  -> <= fraction of the PDP8 run (opt only)
    #   CO2_CAP=plan      -> Decision 768 ceiling: 197-199 Mt in 2030 -> 27 Mt in 2050, linear (both scenarios, v5)
    #   CO2_CAP=<number>  -> absolute cap in Mt (0 = zero-CO2 power sector; imports/biomass counted as zero)
    if CAP != "none":
        if CAP == "plan":
            cap_t = 198.0 + (27.0 - 198.0) * (YEAR - 2030) / 20
        elif CAP.startswith("pdp8"):
            f_ = float(CAP.split("*")[1]) if "*" in CAP else 1.0
            cap_t = f_ * json.loads((RES / f"{YEAR}_pdp8{P8TAG}_summary.json").read_text())["co2_Mt"]
        else:
            cap_t = float(CAP)
        print(f"CO2 cap {cap_t:.1f} Mt ({CAP})")
        n.add("GlobalConstraint", "CO2", type="primary_energy", carrier_attribute="co2_emissions", sense="<=",
              constant=cap_t * 1e6)

LK_MIN0 = n.links.p_nom_min.copy()  # existing (+ plan) corridor capacity: expansion cost is counted above this
FIX_FROM = os.environ.get("FIX_FROM", "")  # v5 adequacy/regret: dispatch the solved portfolio of that run
NO_RESERVE = os.environ.get("NO_RESERVE", "0") != "0"  # drop reserve/limit constraints (energy adequacy test)
if FIX_FROM:
    prev = pypsa.Network(RES / f"{FIX_FROM}.nc")
    for comp in ["generators", "storage_units", "links"]:
        df, dp = getattr(n, comp), getattr(prev, comp)
        ext = df.index[df.p_nom_extendable]
        df.loc[ext, "p_nom"] = dp.p_nom_opt.reindex(ext).fillna(0.0).values
        df.loc[ext, "p_nom_min"] = np.minimum(df.loc[ext, "p_nom_min"].values, df.loc[ext, "p_nom"].values)
        df.loc[ext, "p_nom_extendable"] = False
    SX = float(os.environ.get("SOLAR_NEW_X", "1"))  # slower PV build-out: scale the portfolio's new utility PV
    if SX != 1:
        sn_ = n.generators.index[(n.generators.carrier == "solar") & n.generators.index.str.contains(" new")]
        n.generators.loc[sn_, "p_nom"] *= SX
    BX = float(os.environ.get("BAT_NEW_X", "1"))  # battery delivery shortfall: scale all batteries of the portfolio
    if BX != 1:
        bt_ = n.storage_units.index[n.storage_units.carrier == "battery"]
        n.storage_units.loc[bt_, "p_nom"] *= BX
    NX = float(os.environ.get("NORTH_CORR_X", "1"))  # outage on the corridors into the North: scale their capacity
    if NX != 1:
        NORTH_ = cl.index[cl.region == "Bắc"]
        cr_ = n.links.index[n.links.bus0.isin(NORTH_) ^ n.links.bus1.isin(NORTH_)]
        n.links.loc[cr_, "p_nom"] *= NX
    print(f"FIX_FROM={FIX_FROM}: all capacities fixed (SOLAR_NEW_X={SX}, BAT_NEW_X={BX}, NORTH_CORR_X={NX})")
OUTAGE_SEED = os.environ.get("OUTAGE_SEED", "")
if OUTAGE_SEED:  # stochastic forced outages: weekly binomial unit outages per region and carrier (planned share kept)
    rng = np.random.default_rng(int(OUTAGE_SEED))
    FOR = {"coal": 0.075, "gas": 0.06, "LNG": 0.06, "OCGT": 0.05, "nuclear": 0.05, "oil": 0.10, "biomass": 0.10}
    UNIT = {"coal": 600, "gas": 400, "LNG": 800, "OCGT": 250, "nuclear": 1100, "oil": 100, "biomass": 50}
    wk = np.arange(len(n.snapshots)) // 168
    av = {}
    for g_, r_ in n.generators[n.generators.carrier.isin(list(FOR))].iterrows():
        c_ = r_.carrier
        k_ = max(1, int(round(r_.p_nom / UNIT[c_])))
        out_w = rng.binomial(k_, FOR[c_], size=wk.max() + 1)
        av[g_] = (AVAIL[c_] / (1 - FOR[c_])) * (1 - out_w[wk] / k_)
    n.generators_t.p_max_pu = pd.concat([n.generators_t.p_max_pu, pd.DataFrame(av, index=n.snapshots)], axis=1)
    print(f"OUTAGE_SEED={OUTAGE_SEED}: {len(av)} thermal generators with weekly forced outages")
if PATH_FROM:  # v5 pathway: capacity built in the earlier solved year stays (p_nom_min), lifetimes >= 20 a
    prev = pypsa.Network(RES / f"{PATH_FROM}.nc")
    for comp in ["generators", "storage_units", "links"]:
        df, dp = getattr(n, comp), getattr(prev, comp)
        ext = df.index[df.p_nom_extendable].intersection(dp.index[dp.p_nom_extendable])
        df.loc[ext, "p_nom_min"] = np.maximum(df.loc[ext, "p_nom_min"].values, dp.p_nom_opt.reindex(ext).values)
        df.loc[ext, "p_nom_max"] = np.maximum(df.loc[ext, "p_nom_max"].values, df.loc[ext, "p_nom_min"].values)
    print(f"PATH_FROM={PATH_FROM}: minimum capacities from the earlier year applied")

# ---------------- coal unit commitment (linearised) ----------------
if UC:
    cg = n.generators.index[n.generators.carrier == "coal"]
    n.generators.loc[cg, "committable"] = True
    n.generators.loc[cg, "p_min_pu"] = COAL_MIN
    n.generators.loc[cg, "start_up_cost"] = COAL_SU * n.generators.loc[cg, "p_nom"]
NORTH = cl.index[cl.region == "Bắc"]
PN_t = float(load[NORTH].sum(axis=1).max())  # northern (non-coincident) peak, MW

# ---------------- time aggregation & solve ----------------
w = int(RESAMPLE[:-1])
m2 = n.copy()
sn = snap[::w]
tot_load = n.loads_t.p_set.sum(axis=1)
peak_day = tot_load.idxmax().normalize()
keep = sn[((sn.dayofyear - 1) % DSTEP == 0) | (sn.normalize() == peak_day)] if DSTEP > 1 else sn
m2.set_snapshots(keep)
m2.snapshot_weightings.loc[:, :] = w * len(sn) / len(keep)
if STORE_W and DSTEP > 1:
    # v5: state of charge moves with the true step length (3 h), not with the representation weight (12 h), so that
    # 4 h batteries and pumped hydro cycle correctly within each retained day. Retained days are chained, i.e. one
    # day of net inflow per DSTEP days: the seasonal hydro reservoir is scaled by the same factor.
    m2.snapshot_weightings["stores"] = float(w)
    fac_ = w / float(m2.snapshot_weightings.generators.iloc[0])
    hy_ = m2.storage_units.index[m2.storage_units.carrier == "hydro"]
    m2.storage_units.loc[hy_, "max_hours"] *= fac_
if UC:  # start-up costs are not snapshot-weighted in PyPSA: scale sampled-day cycles to the full year
    m2.generators.loc[m2.generators.committable, "start_up_cost"] *= len(sn) / len(keep)
print(f'snapshots {len(keep)} (DAY_STEP={DSTEP}), weight {w * len(sn) / len(keep):.2f}')
for comp, attrs in [("Load", ["p_set"]), ("Generator", ["p_max_pu"]), ("StorageUnit", ["inflow"])]:
    df_dict = getattr(n, comp.lower() + "s_t" if comp != "StorageUnit" else "storage_units_t")
    for at in attrs:
        src = df_dict[at]
        if len(src.columns):
            agg = src.groupby(np.arange(len(src)) // w).mean()
            agg.index = sn
            agg = agg.loc[keep]
            getattr(m2, comp.lower() + "s_t" if comp != "StorageUnit" else "storage_units_t")[at] = agg
n = m2
import xarray as xr  # noqa: E402


def firm(n_):
    """firm capacity of fixed assets (MW) with CREDIT."""
    g = n_.generators[~n_.generators.p_nom_extendable & (n_.generators.carrier != "load shedding")]
    s_ = n_.storage_units[~n_.storage_units.p_nom_extendable]
    return float((g.p_nom * g.carrier.map(CREDIT).fillna(0)).sum() + (s_.p_nom * s_.carrier.map(CREDIT).fillna(0)).sum())


def bat_firm(b_mw):
    """firm contribution (MW) of b_mw of 4 h batteries under the declining tranche credits."""
    rem, out_ = b_mw, 0.0
    for sh, cr in BAT_TRANCHES:
        take = rem if sh is None else min(rem, sh * P_t)
        out_ += take * cr * BAT_SCALE
        rem -= take
    return out_


def reserve(n_, sn_):
    m_ = n_.model
    gen, su, lk = n_.generators, n_.storage_units, n_.links

    def lin(var, weights):
        if var not in m_.variables:
            return 0
        v_ = m_[var]
        dim = v_.dims[0]
        idx = v_.coords[dim].values
        return (v_ * xr.DataArray(weights.reindex(idx).fillna(0).values.astype(float), coords={dim: idx})).sum()

    cr_g = gen.carrier.map(CREDIT).fillna(0)
    cr_s = su.carrier.map(CREDIT).fillna(0)
    bat = su.carrier == "battery"
    cross = (lk.bus0.isin(NORTH) ^ lk.bus1.isin(NORTH)).astype(float)
    if CRM == "hourly":
        hourly_reserve(n_, m_, gen, su, lk, cr_g, cross, lin)
    else:
        static_reserve(n_, m_, gen, su, lk, cr_g, cr_s, bat, cross, lin)
    extra_constraints(n_, m_, gen, su, lk)


THERM = ["coal", "gas", "LNG", "OCGT", "oil", "nuclear", "biomass"]
VREC = ["solar", "rooftop", "onwind", "offwind"]


def _da(values, name, idx):
    return xr.DataArray(np.asarray(values, dtype=float), coords=[(name, idx)])


def hourly_reserve(n_, m_, gen, su, lk, cr_g, cross, lin):
    """v5 chronological capacity reserve margin (GenX-style CRM), national and northern, in every snapshot:
    derated dispatchable capacity + available wind/solar + scheduled net output of storage, hydro and imports
    (+ northern import capability) >= margin x load x (hourly peak / 3 h peak)."""
    snaps = n_.snapshots
    pmax = n_.generators_t.p_max_pu
    lt_ = n_.loads_t.p_set
    for region, margin, Pk, nm_ in [(None, RESERVE_MARGIN, P_t, "capacity_reserve_margin"),
                                    (NORTH, NORTH_MARGIN, PN_t, "north_reserve_margin")]:
        ing = gen.bus.isin(region) if region is not None else pd.Series(True, index=gen.index)
        ins = su.bus.isin(region) if region is not None else pd.Series(True, index=su.index)
        loads = n_.loads.index[n_.loads.bus.isin(region)] if region is not None else n_.loads.index
        ld = lt_[loads].sum(axis=1)
        rhs = margin * ld * (Pk / float(ld.max()))
        th = ing & gen.carrier.isin(THERM)
        const = float((gen.p_nom * cr_g)[th & ~gen.p_nom_extendable].sum())
        vf = gen.index[ing & gen.carrier.isin(VREC) & ~gen.p_nom_extendable]
        const_t = (pmax.reindex(columns=vf).fillna(1.0) * gen.p_nom[vf]).sum(axis=1)
        lhs = lin("Generator-p_nom", cr_g.where(th, 0))
        ve = gen.index[ing & gen.carrier.isin(VREC) & gen.p_nom_extendable]
        if len(ve):
            coef = xr.DataArray(pmax.reindex(columns=ve).fillna(1.0).values, coords=[("snapshot", snaps), ("name", ve)])
            lhs = lhs + (m_["Generator-p_nom"].sel(name=ve) * coef).sum("name")
        sus = su.index[ins]
        if len(sus):
            lhs = lhs + m_["StorageUnit-p_dispatch"].sel(name=sus).sum("name") - m_["StorageUnit-p_store"].sel(name=sus).sum("name")
        imps = gen.index[ing & (gen.carrier == "imports")]
        if len(imps):
            lhs = lhs + m_["Generator-p"].sel(name=imps).sum("name")
        if RELAX_SHED:
            shd = gen.index[ing & (gen.carrier == "load shedding")]
            lhs = lhs + margin * (Pk / float(ld.max())) * m_["Generator-p"].sel(name=shd).sum("name")
        if region is not None:  # import capability of corridors into the region (NTC-style, ENTSO-E ERAA)
            lhs = lhs + lin("Link-p_nom", cross)
            const += float((lk.p_nom * cross)[~lk.p_nom_extendable].sum())
        m_.add_constraints(lhs >= _da((rhs - const_t - const).values, "snapshot", snaps), name=nm_)


def static_reserve(n_, m_, gen, su, lk, cr_g, cr_s, bat, cross, lin):
    """v4: credits at the annual peak, batteries through declining-credit tranches."""
    bat_fix = float(su.p_nom[bat & ~su.p_nom_extendable].sum())  # static (v4) formulation
    tr = m_.add_variables(lower=0, coords=[pd.RangeIndex(len(BAT_TRANCHES), name="tranche")], name="battery_tranche")
    for i_, (sh, cr) in enumerate(BAT_TRANCHES):
        if sh is not None:
            m_.add_constraints(tr.sel(tranche=i_) <= sh * P_t, name=f"battery_tranche_cap_{i_}")
    m_.add_constraints(tr.sum() - lin("StorageUnit-p_nom", bat.astype(float)) == bat_fix, name="battery_tranche_sum")
    crs = xr.DataArray([cr * BAT_SCALE for _, cr in BAT_TRANCHES], coords={"tranche": range(len(BAT_TRANCHES))})
    lhs = lin("Generator-p_nom", cr_g) + lin("StorageUnit-p_nom", cr_s) + (tr * crs).sum()
    m_.add_constraints(lhs >= RESERVE_MARGIN * P_t - firm(n_), name="capacity_reserve_margin")
    # northern adequacy: local firm capacity (batteries at the middle tranche credit) + import capability
    inN_g, inN_s = gen.bus.isin(NORTH), su.bus.isin(NORTH)
    cr_sN = (cr_s + bat * 0.7 * BAT_SCALE).where(inN_s, 0)
    lhsN = lin("Generator-p_nom", cr_g.where(inN_g, 0)) + lin("StorageUnit-p_nom", cr_sN) + lin("Link-p_nom", cross)
    fixN = float((gen.p_nom * cr_g)[inN_g & ~gen.p_nom_extendable].sum() + (su.p_nom * cr_sN)[~su.p_nom_extendable].sum()
                 + (lk.p_nom * cross)[~lk.p_nom_extendable].sum())
    m_.add_constraints(lhsN >= NORTH_MARGIN * PN_t - fixN, name="north_reserve_margin")


def hydro_monthly(n_, sn_=None):
    m_, su = n_.model, n_.storage_units
    hy = su.index[su.carrier == "hydro"]
    pd_ = m_["StorageUnit-p_dispatch"].sel(name=hy)
    infl_ = n_.storage_units_t.inflow.reindex(columns=hy).fillna(0.0)
    wg = n_.snapshot_weightings.generators
    for mth in range(1, 13):
        sm = n_.snapshots[n_.snapshots.month == mth]
        if not len(sm):
            continue
        lhs = (pd_.sel(snapshot=sm) * _da(wg[sm].values, "snapshot", sm)).sum("snapshot")
        m_.add_constraints(lhs <= _da(infl_.loc[sm].mul(wg[sm], axis=0).sum().values, "name", hy),
                           name=f"hydro_monthly_budget_{mth}")


def extra_constraints(n_, m_, gen, su, lk):
    if HYDRO_MONTHLY:
        hydro_monthly(n_)
    # national pumped-hydro limit: Decision 768 upper path (6.0 GW 2030 -> 21.327 GW 2050, linear; site/lead-time
    # limited). Without it the optimiser builds 3 GW at every hydro region (51 GW in 2035).
    # build-rate limits (Vietnam record years sustained every year 2025..YEAR): solar 11 GW/yr (2020, incl. rooftop),
    # onshore wind 3.6 GW/yr (2021); offshore wind <= Decision 768 path; fixed PDP8 additions count against the limits
    if "Generator-p_nom" in m_.variables:
        gv = m_["Generator-p_nom"]
        for car, lim in ([("solar", BUILD["solar"]), ("onwind", BUILD["onwind"]), ("offwind", BUILD["offwind"])] if BUILD_LIMIT else []):
            idx = gen.index[(gen.carrier == car) & gen.p_nom_extendable]
            fixed_new = float(gen.p_nom[(gen.carrier == car) & ~gen.p_nom_extendable & gen.index.str.contains(" new")].sum())
            if len(idx):
                m_.add_constraints(gv.sel({gv.dims[0]: idx}).sum() <= max(lim - fixed_new, 0), name=f"build_limit_{car}")
    phs = su.index[(su.carrier == "PHS") & su.p_nom_extendable]
    if len(phs) and "StorageUnit-p_nom" in m_.variables:
        v_ = m_["StorageUnit-p_nom"]
        phs_fix = float(su.p_nom[(su.carrier == "PHS") & ~su.p_nom_extendable].sum())
        m_.add_constraints(v_.sel({v_.dims[0]: phs}).sum() <= max(PHS_MAX_MW - phs_fix, 0), name="phs_national_potential")
    sv = m_["StorageUnit-p_nom"] if "StorageUnit-p_nom" in m_.variables else None
    if BAT_BUILD and sv is not None:  # battery build-rate limit (sensitivity)
        be = su.index[(su.carrier == "battery") & su.p_nom_extendable]
        fixb = float(su.p_nom[(su.carrier == "battery") & ~su.p_nom_extendable].sum())
        m_.add_constraints(sv.sel(name=be).sum() <= max(BAT_BUILD * 1e3 * (_Y - 2024) - fixb, 0), name="build_limit_battery")
    if STOR_ONLY:  # the plan's national storage totals, siting optimised
        bfx = pdp8_caps(YEAR)
        for car_, key_ in [("battery", "battery"), ("PHS", "PHS")]:
            ix_ = su.index[(su.carrier == car_) & su.p_nom_extendable]
            m_.add_constraints(sv.sel(name=ix_).sum() == bfx[key_] * 1e3, name=f"plan_storage_total_{car_}")
    if OPRES:
        opres_snsp(n_, m_, gen, su, sv)
    extra_constraints_tail(n_, m_, gen, su, lk)


def opres_snsp(n_, m_, gen, su, sv):
    """operating reserve (largest unit + 5 % of VRE output) and SNSP limit in every snapshot (v5)."""
    snaps = n_.snapshots
    if True:
        P_ = m_["Generator-p"]
        com = gen.index[gen.committable]
        oth = gen.index[gen.carrier.isin(THERM) & ~gen.committable]
        of_, oe_ = oth[~gen.p_nom_extendable[oth].values], oth[gen.p_nom_extendable[oth].values]
        hr = -P_.sel(name=gen.index[gen.carrier.isin(THERM)]).sum("name")
        if len(com):
            hr = hr + (m_["Generator-status"].sel(name=com) * _da((gen.p_nom[com] * gen.p_max_pu[com]).values, "name", com)).sum("name")
        if len(oe_):
            hr = hr + (m_["Generator-p_nom"].sel(name=oe_) * _da(gen.p_max_pu[oe_].values, "name", oe_)).sum()
        hconst = float((gen.p_nom[of_] * gen.p_max_pu[of_]).sum()) + float(su.p_nom[~su.p_nom_extendable].sum())
        se_ = su.index[su.p_nom_extendable]
        if len(se_):
            hr = hr + sv.sel(name=se_).sum()
        hr = hr - m_["StorageUnit-p_dispatch"].sum("name") + m_["StorageUnit-p_store"].sum("name")
        vre_out = P_.sel(name=gen.index[gen.carrier.isin(VREC)]).sum("name")
        m_.add_constraints(hr - OPRES_VRE * vre_out >= OPRES_UNIT_MW - hconst, name="operating_reserve")
        ld = n_.loads_t.p_set.sum(axis=1)
        # SNSP (EirGrid definition): non-synchronous output <= SNSP_MAX x (demand + storage charging), i.e. synchronous
        # output (thermal, hydro, pumped hydro, AC imports from Laos/China) >= (1 - SNSP_MAX) x (demand + charging)
        sync = P_.sel(name=gen.index[gen.carrier.isin(THERM + ["imports"])]).sum("name") + \
            m_["StorageUnit-p_dispatch"].sel(name=su.index[su.carrier.isin(["hydro", "PHS"])]).sum("name")
        if RELAX_SHED:
            sync = sync + (1 - SNSP_MAX) * P_.sel(name=gen.index[gen.carrier == "load shedding"]).sum("name")
        m_.add_constraints(sync - (1 - SNSP_MAX) * m_["StorageUnit-p_store"].sum("name")
                           >= _da(((1 - SNSP_MAX) * ld).values, "snapshot", snaps), name="snsp")


def extra_constraints_tail(n_, m_, gen, su, lk):
    if PLAN_RANGE:  # national capacities within the Decision 768 low..high range (OCGT: lower bound only, top-up allowed)
        lo_, hi_ = pdp8_caps(YEAR, P768_LOW), pdp8_caps(YEAR, P768_HIGH)
        lo_["LNG"] = hi_["LNG"] = pdp8_caps(YEAR)["LNG"]
        for key, df, var, cars in [("solar_total", gen, "Generator-p_nom", ["solar", "rooftop"]),
                                   ("onwind", gen, "Generator-p_nom", ["onwind"]), ("offwind", gen, "Generator-p_nom", ["offwind"]),
                                   ("nuclear", gen, "Generator-p_nom", ["nuclear"]), ("LNG", gen, "Generator-p_nom", ["LNG"]),
                                   ("flexible", gen, "Generator-p_nom", ["OCGT"]), ("battery", su, "StorageUnit-p_nom", ["battery"]),
                                   ("PHS", su, "StorageUnit-p_nom", ["PHS"])]:
            sel_ = df.carrier.isin(cars)
            fixed_ = float(df.p_nom[sel_ & ~df.p_nom_extendable].sum())
            ext_ = df.index[sel_ & df.p_nom_extendable]
            if not len(ext_):
                continue
            expr = m_[var].sel(name=ext_).sum()
            m_.add_constraints(expr >= lo_[key] * 1e3 - fixed_, name=f"plan_range_lo_{key}")
            if key != "flexible":
                m_.add_constraints(expr <= max(hi_[key] * 1e3 - fixed_, 0), name=f"plan_range_hi_{key}")
    if MGA:  # near-optimal: maximise a group's capacity at total cost <= (1 + eps) x optimum (same settings)
        grp, eps = MGA.split(":")
        ref = json.loads(Path(MGA_REF).read_text())["objective"]
        # scaled to million USD (coefficients up to 2e6 USD/MW otherwise give barrier numerical trouble)
        m_.add_constraints(1e-6 * m_.objective.expression <= 1e-6 * (1 + float(eps)) * ref, name="mga_budget")
        if grp == "ac":
            ac_ = lk.index[(lk.carrier == "AC") & lk.p_nom_extendable]
            target = (m_["Link-p_nom"].sel(name=ac_) * _da(lk.length[ac_].values / 1e3, "name", ac_)).sum()  # GW km
        else:
            car = {"lng": "LNG", "offwind": "offwind", "nuclear": "nuclear"}[grp]
            target = m_["Generator-p_nom"].sel(name=gen.index[(gen.carrier == car) & gen.p_nom_extendable]).sum()
        m_.objective = -1e-3 * target  # GW (or TW km)


SOLVER = os.environ.get("SOLVER", "highs")  # gurobi: barrier without crossover (academic licence), same tolerance
if SOLVER == "gurobi":
    SOLVER_OPTS = {"Method": 2, "Crossover": 1 if CROSSOVER else 0, "BarConvTol": 1e-4, "FeasibilityTol": 1e-5,
                   "OptimalityTol": 1e-5, "Threads": int(os.environ.get("THREADS", "4")), "Seed": 123,
                   "LogFile": str(RES / f"gurobi_{YEAR}_{SCEN}{TAG}.log"), "LogToConsole": 0}
    if MGA:  # near-optimal runs: cost budget row couples all variables -> homogeneous barrier, numeric focus
        SOLVER_OPTS.update({"BarHomogeneous": 1, "NumericFocus": 2})
else:
    SOLVER_OPTS = {"solver": "ipm", "run_crossover": "on" if CROSSOVER else "off", "threads": 4, "log_to_console": False,
                   "log_file": str(RES / f"highs_{YEAR}_{SCEN}{TAG}.log"), "small_matrix_value": 1e-6,
                   "large_matrix_value": 1e9, "primal_feasibility_tolerance": 1e-5,
                   "dual_feasibility_tolerance": 1e-5, "ipm_optimality_tolerance": 1e-3,  # 0.1 % gap (~0.03 bn USD/yr)
                   "random_seed": 123}
def fixed_dispatch(n_, sn_=None):
    """fixed-portfolio dispatch (adequacy/regret): no capacity reserve margin, but monthly hydro budgets, operating
    reserve and SNSP limit as in the optimisation (v6); shortfalls relieve them (RELAX_SHED)."""
    if HYDRO_MONTHLY:
        hydro_monthly(n_)
    if OPRES and os.environ.get("KEEP_OPRES", "1" if V6 else "0") != "0":
        sv_ = n_.model["StorageUnit-p_nom"] if "StorageUnit-p_nom" in n_.model.variables else None
        opres_snsp(n_, n_.model, n_.generators, n_.storage_units, sv_)


status = n.optimize(solver_name=SOLVER, extra_functionality=fixed_dispatch if NO_RESERVE else reserve,
                    linearized_unit_commitment=UC, solver_options=SOLVER_OPTS)
print("status", status)

# ---------------- summary ----------------
wts = n.snapshot_weightings.generators
gp = n.generators_t.p.mul(wts, axis=0).sum()
sp = n.storage_units_t.p.clip(lower=0).mul(wts, axis=0).sum()
energy = pd.concat([gp.groupby(n.generators.carrier).sum(), sp.groupby(n.storage_units.carrier).sum()]) / 1e6
eff = n.generators.efficiency.where(n.generators.efficiency > 0, 1)
co2_t = (gp / eff * n.generators.carrier.map(n.carriers.co2_emissions)).sum()
capg = n.generators.p_nom_opt.where(n.generators.p_nom_extendable, n.generators.p_nom)
caps_out = pd.concat([capg[n.generators.carrier != "load shedding"].groupby(n.generators.carrier).sum(),
                      n.storage_units.p_nom_opt.where(n.storage_units.p_nom_extendable, n.storage_units.p_nom)
                      .groupby(n.storage_units.carrier).sum()]) / 1e3
new_g = n.generators.index.str.contains(" new")
new_s = n.storage_units.carrier.isin(["battery", "PHS"])
ann_capex = (capg[new_g] * n.generators.capital_cost[new_g]).sum() + \
    (n.storage_units.p_nom_opt.where(n.storage_units.p_nom_extendable, n.storage_units.p_nom)[new_s] *
     n.storage_units.capital_cost[new_s]).sum()
lk = n.links
lnom = lk.p_nom_opt.where(lk.p_nom_extendable, lk.p_nom)
ac_ann = annuity(C.loc["HVAC_line", "life"]) + C.loc["HVAC_line", "fom_pct"] / 100
if SCEN == "pdp8" and "ac" not in RELEASE and not BENCH:
    ac_add = pd.Series(allp.p_nom_added.values, index="AC " + allp.index)
    # cost of ALL Decision 1509 lines of the period (incl. intra-region), circuits x rating x km (line cost only)
    Lall = pd.read_csv(DATA / "plans" / "qd1509_lines.csv")
    Lall = Lall[Lall.period.isin(["2025-2030"] + (["2031-2035"] if YEAR >= 2035 else []))]
    rating = np.where(Lall.kv == 500, C.loc["AC_500_circuit_MW", "vom_usd_mwh"], C.loc["AC_220_circuit_MW", "vom_usd_mwh"])
    mwkm_all = float((Lall.circuits.fillna(2) * rating * Lall.km).sum())
    lk_cost = mwkm_all * C.loc["HVAC_line", "capex_usd_kw"] * ac_ann
    dc = lk[lk.carrier == "DC"]
    lk_cost += sum(dc.p_nom[i] * (dc.length[i] * C.loc["HVDC_line", "capex_usd_kw"] * (annuity(C.loc["HVDC_line", "life"]) +
                                  C.loc["HVDC_line", "fom_pct"] / 100) + capcost("HVDC_converter_pair")) for i in dc.index)
    tx_add_gw = {"AC_interregion_TWkm": float((ac_add / CORRIDOR_DERATE * lk.length.reindex(ac_add.index)).sum() / 1e6),
                 "AC_all_lines_TWkm": mwkm_all / 1e6, "HVDC_GW": float(dc.p_nom.sum() / 1e3),
                 "HVDC_TWkm": float((dc.p_nom * dc.length).sum() / 1e6)}
    tx_overnight = mwkm_all * C.loc["HVAC_line", "capex_usd_kw"] / 1e9 + float(sum(
        dc.p_nom[i] * (dc.length[i] * C.loc["HVDC_line", "capex_usd_kw"] + C.loc["HVDC_converter_pair", "capex_usd_kw"] * 1e3)
        for i in dc.index)) / 1e9
else:
    lk_cost = ((lnom - LK_MIN0.reindex(lk.index)) * lk.capital_cost).sum()  # LK_MIN0: before PATH_FROM
    dadd = (lnom - LK_MIN0.reindex(lk.index))
    tx_add_gw = {"AC_interregion_TWkm": float((dadd * lk.length)[lk.carrier == "AC"].sum() / CORRIDOR_DERATE / 1e6),
                 "HVDC_GW": float(lnom[lk.carrier == "DC"].sum() / 1e3),
                 "HVDC_TWkm": float((lnom * lk.length)[lk.carrier == "DC"].sum() / 1e6)}
    tx_overnight = float(((dadd / CORRIDOR_DERATE * lk.length)[lk.carrier == "AC"]).sum() * C.loc["HVAC_line", "capex_usd_kw"] / 1e9
                         + sum(lnom[i] * (lk.length[i] * C.loc["HVDC_line", "capex_usd_kw"] + C.loc["HVDC_converter_pair", "capex_usd_kw"] * 1e3)
                               for i in lk.index[lk.carrier == "DC"]) / 1e9)
    # intra-region grid (Decision 1509 lines not crossing region borders) is not modelled in the transport model;
    # ASSUMPTION: needed in both scenarios -> add the PDP8 intra-region line volume as a common cost item
    p8 = json.loads((RES / f"{YEAR}_pdp8{P8TAG}_summary.json").read_text())["transmission_added"] if not BENCH else {}
    intra_mwkm = max(p8.get("AC_all_lines_TWkm", 0) - p8.get("AC_interregion_TWkm", 0), 0) * 1e6
    lk_cost += intra_mwkm * C.loc["HVAC_line", "capex_usd_kw"] * ac_ann
    tx_overnight += intra_mwkm * C.loc["HVAC_line", "capex_usd_kw"] / 1e9
    tx_add_gw["AC_intraregion_common_TWkm"] = intra_mwkm / 1e6
opex = (gp * n.generators.marginal_cost).sum()
su_cost = 0.0
if UC and "start_up" in n.generators_t and len(n.generators_t.start_up.columns):
    su_cost = float((n.generators_t.start_up * n.generators.start_up_cost.reindex(n.generators_t.start_up.columns)).sum().sum())
opex += su_cost
_g = n.generators[n.generators.carrier != "load shedding"]
_s = n.storage_units
_scap = _s.p_nom_opt.where(_s.p_nom_extendable, _s.p_nom)
firm_out = float(((_g.p_nom_opt.where(_g.p_nom_extendable, _g.p_nom)) * _g.carrier.map(CREDIT).fillna(0)).sum() +
                 (_scap * _s.carrier.map(CREDIT).fillna(0)).sum() + bat_firm(float(_scap[_s.carrier == "battery"].sum()))) / 1e3
avail = (n.generators_t.p_max_pu.reindex(columns=n.generators.index).fillna(1.0) * capg).mul(wts, axis=0).sum()
vre_g = n.generators.carrier.isin(["solar", "rooftop", "onwind", "offwind"])
curt = float((avail[vre_g] - gp[vre_g]).sum() / 1e6)
# v5 diagnostics: implied capacity credits (mean net output in the 10 snapshots of highest net load / capacity),
# maximum instantaneous non-synchronous share (VRE + battery discharge over load)
vre_av = (n.generators_t.p_max_pu.reindex(columns=n.generators.index[vre_g]).fillna(0) * capg[vre_g]).sum(axis=1)
ld_t = n.loads_t.p_set.sum(axis=1)
top_ = (ld_t - vre_av).nlargest(10).index
implied = {}
for car in ["battery", "PHS", "hydro"]:
    cols = n.storage_units.index[n.storage_units.carrier == car]
    capc = float(_scap[cols].sum())
    if capc > 1:
        implied[car] = float(n.storage_units_t.p.loc[top_, cols].sum(axis=1).mean() / capc)
imp_c = n.generators.index[n.generators.carrier == "imports"]
implied["imports"] = float(n.generators_t.p.loc[top_, imp_c].sum(axis=1).mean() / max(float(capg[imp_c].sum()), 1))
implied["onwind"] = float((n.generators_t.p_max_pu.reindex(columns=n.generators.index[n.generators.carrier == "onwind"]).fillna(0)
                            * capg[n.generators.carrier == "onwind"]).loc[top_].sum(axis=1).mean() / max(float(capg[n.generators.carrier == "onwind"].sum()), 1))
bat_d = n.storage_units_t.p_dispatch.reindex(columns=n.storage_units.index[n.storage_units.carrier == "battery"]).sum(axis=1) \
    if "p_dispatch" in n.storage_units_t else 0
charge_t = n.storage_units_t.p_store.sum(axis=1) if "p_store" in n.storage_units_t else 0
nonsync = (n.generators_t.p.reindex(columns=n.generators.index[vre_g]).sum(axis=1) + bat_d) / (ld_t + charge_t)  # EirGrid def.
try:
    obj_val = float(n.objective)
except (TypeError, AttributeError):
    obj_val = None
extra_ind = {"reserve_margin_pct": 100 * firm_out * 1e3 / P_t, "curtailment_TWh": curt,
             "implied_credit_top10": implied, "snsp_max_pct": float(100 * nonsync.max()),
             "net_peak_snapshot_hour": int(top_[0].hour), "crm": CRM, "opres": OPRES, "store_w": bool(STORE_W),
             "lole_h": float(((n.generators_t.p[n.generators.index[n.generators.carrier == "load shedding"]].sum(axis=1) > 1)
                              * wts).sum()), "weather_year": WY or "2024", "fix_from": FIX_FROM,
             "curtailment_pct": 100 * curt / max(float(avail[vre_g].sum() / 1e6), 1e-9), "startup_cost_bnUSD": su_cost / 1e9,
             "storage_energy_GWh": float((_scap * n.storage_units.max_hours)[n.storage_units.carrier.isin(["battery", "PHS"])].sum() / 1e3),
             "north_peak_GW": PN_t / 1e3, "uc": UC}
shed = energy.get("load shedding", 0.0)
overnight = {}
techmap = {"solar": "solar", "onwind": "onwind", "offwind": "offwind", "LNG": "CCGT", "OCGT": "OCGT", "nuclear": "nuclear"}
for t, tech in techmap.items():
    mw = capg[new_g & (n.generators.carrier == t)].sum()
    overnight[t] = float(mw * C.loc[tech, "capex_usd_kw"] * 1e3 / 1e9)
for t, tech in [("battery", "battery_4h"), ("PHS", "PHS")]:
    mw = n.storage_units.p_nom_opt.where(n.storage_units.p_nom_extendable, n.storage_units.p_nom)[n.storage_units.carrier == t].sum()
    overnight[t] = float(mw * C.loc[tech, "capex_usd_kw"] * 1e3 / 1e9)
out = {"year": YEAR, "scenario": SCEN, "demand_TWh": float(E_t / 1e6), "pmax_GW": float(P_t / 1e3),
       "extra_load": EXTRA, "extra_TWh": float(extra.values.sum() / 1e6), "extra_peak_MW": float(extra.sum(axis=1).max()),
       "costs_file": CFILE.name, "co2_cap": os.environ.get("CO2_CAP", "none"), "objective": obj_val, "plan_variant": PLAN, "model_v": int(MODEL_V_),
       "ocgt_topup_GW": float(capg[n.generators.index.str.contains("OCGT new topup")].sum() / 1e3), "vre_alloc": os.environ.get("ALLOC", "qd1509") if SCEN == "pdp8" else "", "lng_qc_cf": LNG_QC if SCEN == "pdp8" else 0.0, "sensitivity": SENS, "vre_src": VRE_SRC,
       "co2_Mt": float(co2_t / 1e6), "load_shedding_TWh": float(shed),
       "co2_shadow_USD_per_t": abs(float(n.global_constraints.mu.get("CO2", 0.0))) if "CO2" in n.global_constraints.index else 0.0,
       "cost_bnUSD_per_year": {"annualised_new_gen_storage": float(ann_capex / 1e9), "annualised_new_transmission": float(lk_cost / 1e9),
                               "fuel_and_VOM": float((opex - shed * 1e6 * C.loc["VOLL", "vom_usd_mwh"]) / 1e9),
                               "unserved_energy_at_VOLL": float(shed * 1e6 * C.loc["VOLL", "vom_usd_mwh"] / 1e9)},
       "overnight_investment_new_bnUSD": overnight | {"transmission_lines": tx_overnight},
       "transmission_added": tx_add_gw, "firm_capacity_GW": firm_out, "reserve_requirement_GW": RESERVE_MARGIN * P_t / 1e3,
       "indicators": extra_ind,
       "capacity_GW": caps_out.round(2).to_dict(), "energy_TWh": energy.round(2).to_dict()}
out["cost_bnUSD_per_year"]["total_excl_VOLL"] = sum(v for k, v in out["cost_bnUSD_per_year"].items() if k != "unserved_energy_at_VOLL")
(RES / f"{YEAR}_{SCEN}{TAG}_summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
n.export_to_netcdf(RES / f"{YEAR}_{SCEN}{TAG}.nc")
print(json.dumps(out, indent=1, ensure_ascii=False))
