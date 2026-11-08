#!/usr/bin/env python3
"""Vietnam 500/220/110 kV PyPSA network, validation year 2024 (end-2024 fleet).
Source IDs (D-xx datasets, S-xx official documents) -> docs/data_sources.md

Inputs (<DATA> = external drive):
  grid/topology/{buses,lines,transformers}.csv      build_vn_topology.py (OSM)
  plants/vn_units_gem.csv                            build_vn_plants.py (GEM trackers)
  external_data/energydata/small_hydro/existingsmallhydroprojects.geojson   (World Bank, spatial only)
  demand/worldpop/vnm_ppp_2020_1km_Aggregated.tif    (WorldPop 2020, load spatial split)
  shapes/gadm41_VNM_1.json                           (provinces -> power-corporation regions)
  validation/ember_vietnam_monthly_raw.csv           (Ember monthly demand / hydro / imports 2024)
  vietnamgrid/data_model_v2/loads-p_set.csv          (hourly load SHAPE only, EVN-based per paper README)
Outputs: <DATA>/networks/vn2024_base.nc, plants_mapped.csv, load_weights.csv, CALIB.txt
VRE p_max_pu are NOT set here (added by add_vre_profiles_openmeteo.py).
Run: python workflow/scripts/build_vn_network.py
"""
import os
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import json  # noqa: E402

import geopandas as gpd  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
import rasterio  # noqa: E402
import xarray as xr  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402
from substation_mva import match as match_mva  # noqa: E402
from substation_mva import norm as norm_name  # noqa: E402

DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
TOPO = DATA / "grid" / "topology"
OUT = DATA / "networks"
OUT.mkdir(exist_ok=True)
VG = Path(os.environ.get("VIETNAMGRID_DIR", Path(__file__).resolve().parents[3] / "vietnamgrid")) / "data_model_v2"
PVN = Path(os.environ.get("PYPSA_VN_FILE", Path(__file__).resolve().parents[3] / "pypsa-vn" / "vietnam_era5.nc"))  # D-15: 2015-16 ERA5 hydro inflow per bus
YEAR, UTM = 2024, 32648

# ---------------- calibration targets (end-2024 / year 2024), each with source ----------------
CALIB = {
    "energy_TWh": (308.73, "S2 p7 EVN AR 2024-25: production + imports 2024 (=load incl. losses)"),
    "pmax_MW": (49_533, "S4 EVN 21/6/2024: Pmax 19/6/2024"),
    "hydro_MW": (23_664, "S2 p7, incl. small hydro"),
    "wind_MW": (6_000, "S6 Cuc Dien luc 1/2026 p5: wind 'nearly 6 GW' (GEM 6.9 GW scaled)"),
    "solar_farm_MW": (8_900, "S6: solar farms 'nearly 9 GW' AC (GEM PV mixed MWp/MWac scaled)"),
    "solar_rooftop_MW": (8_000, "S6: 87 GW incl. rooftop - 79 GW excl."),
    "imports_MW": (1_222, "S2 p7"),
}
# regional load split proxy: 110 kV transformer MVA 2024 per power corporation (EVN AR 2024-25 p11)
SALES_2024_TWH, SALES_2023_TWH = 276.029, 253.053  # S2 p9 EVN commercial electricity
REGION_MVA = {"NPC": 30_916, "CPC": 8_714, "SPC": 23_951, "HANOI": 9_129, "HCMC": 7_209}
CPC = ["QuảngBình", "QuảngTrị", "ThừaThiênHuế", "ĐàNẵng", "QuảngNam", "QuảngNgãi", "BìnhĐịnh", "PhúYên",
       "KhánhHòa", "KonTum", "GiaLai", "ĐắkLắk", "ĐắkNông"]
SPC = ["NinhThuận", "BìnhThuận", "LâmĐồng", "BìnhPhước", "TâyNinh", "BìnhDương", "ĐồngNai", "BàRịa-VũngTàu",
       "LongAn", "TiềnGiang", "BếnTre", "TràVinh", "VĩnhLong", "ĐồngTháp", "AnGiang", "KiênGiang", "CầnThơ",
       "HậuGiang", "SócTrăng", "BạcLiêu", "CàMau"]
# marginal cost USD/MWh = fuel/eff + VOM. ASSUMPTION (2024 fuel prices: coal ~4.8 USD/GJ, domestic gas ~8.5 USD/GJ,
# FO ~14 USD/GJ) -> to replace with VN Technology Catalogue / EVN-GENCO data
MC = {("coal", "subcritical"): 51, ("coal", "supercritical"): 46, ("coal", "ultra-supercritical"): 44,
      ("coal", "unknown"): 51, ("gas", "combined cycle"): 59, ("gas", "steam turbine"): 90,
      ("oil", "steam turbine"): 160, ("biomass", ""): 30}
VOLL = 3000
# line types per voltage; 500 kV custom from vietnamgrid paper (r,x,b per km), i_nom ASSUMPTION
LINE_TYPE = {500: "VN 500kV 4-bundle", 220: "Al/St 240/40 2-bundle 220.0", 110: "243-AL1/39-ST1A 110.0"}
TRAFO_MVA = {(500, 220): 48_750, (220, 110): 82_375}  # EVN AR p8 totals, split equally per modelled substation
# import points (ASSUMPTION: split; China via Lao Cai/Ha Giang 220 kV, Laos via Pleiku area 220 kV)
IMPORTS = {"CN Lao Cai": (103.97, 22.48, 0.25), "CN Ha Giang": (104.98, 22.82, 0.25), "LA Pleiku": (108.0, 13.98, 0.50)}
PLANT_RE = (r"nhà máy|nmđ|điện gió|điện mặt trời|thủy điện|thuỷ điện|nhiệt điện|sân phân phối|trạm cắt|đmt|"
            r"solar|wind|hydro|power plant")
COUPLE_KM = 3.0  # max distance to couple separately-mapped HV/LV yards of one substation
LOAD_CAP, LOAD_CAP_110 = 0.9, 250  # bus peak load <= 0.9 x connected branch MVA; <= 250 MW at 110 kV (~3x63 MVA)
MAP_KM, MAP_ROOM = 25.0, 0.9  # plant -> bus search radius; usable share of connected branch MVA
BIG_MW, BIG_KM = 600, 15.0  # plants >= BIG_MW connect to a 500 kV bus within BIG_KM if it has room
# plant overrides (S18): Hoa Binh hydro = 8 x 240 MW in 2024 (2 x 240 MW extension grid-synchronised 19/8/2025 and
# 14/11/2025; GEM lists 2,400 MW as operating); units step up to the plant 220 kV switchyard, linked to the 500 kV
# Hoa Binh substation by 2 x 450 MVA autotransformers in 2024 (upgraded to 2 x 900 MVA 2025-26)
PLANT_FIX = {"Hoa Binh hydroelectric plant": {"p_nom": 1920.0, "kv": 220}}
# 500 kV elements missing in OSM (S19): northern section of 500 kV circuit 3 (Quang Trach - Quynh Luu - Thanh Hoa -
# Nam Dinh I - Pho Noi, double circuit, energised 19-27/8/2024; Quynh Luu and Nam Dinh I were junctions without
# substation in 2024) and the Thanh Hoa 500 kV substation (Thieu Hoa, 2 x 600 MVA per evn_500kV.csv; 220 kV side ->
# nearest 220 kV substation Ba Che, ASSUMPTION; the unconfirmed temporary tie into circuit 2 from 6/2024 is ignored).
# 'commissioned': solve_vn.py switches the element off for periods starting before that date.
ADD_BUSES = [("X_ThanhHoa_500", 500, 105.68, 19.90, "Trạm biến áp 500kV Thanh Hóa")]
ADD_LINES = [("S1183902227_500", "X_ThanhHoa_500", 2, 318.0, "2024-08-27",
              "Đường dây 500kV mạch 3 Quảng Trạch - Quỳnh Lưu - Thanh Hóa"),
             ("X_ThanhHoa_500", "S708617218_500", 2, 201.0, "2024-08-19",
              "Đường dây 500kV mạch 3 Thanh Hóa - Nam Định I - Phố Nối")]
ADD_TRAFOS = [("X_ThanhHoa_500", "S484052979_220", "2024-08-19")]
RELAX_110 = 100.0
HYDRO_CF_MAX = 0.9  # max monthly CF of a hydro region
# enforce limits of transformers with compiled substation MVA: 500/220 kV table ~98% of EVN total -> binding;
# 220/110 kV tables cover ~46% of EVN MVA and OSM misses part of the 110 kV grid -> report-only (test week
# Jun 1-7 2024: shedding 3.9% if binding vs 0.0% if not, i.e. artefacts of incomplete data)
TRAFO_ENFORCE = {(500, 220): True, (220, 110): False}

log = []


def hydro_region(lat):
    """N: north of ~17.9N (Ha Tinh/Quang Binh border); C: Central coast + Highlands; S: south of 11.5N."""
    lat = np.asarray(lat, dtype=float)
    return np.where(lat > 17.9, "N", np.where(lat > 11.5, "C", "S"))


def note(s):
    print(s)
    log.append(s)


# ---------------- grid ----------------
buses = pd.read_csv(TOPO / "buses.csv").set_index("bus")
lines = pd.read_csv(TOPO / "lines.csv", index_col=0)
trafos = pd.read_csv(TOPO / "transformers.csv")
trafos["inferred"] = False
buses = pd.concat([buses, pd.DataFrame([{"bus": b_, "v_nom": v_, "x": x_, "y": y_, "substation": b_.rsplit("_", 1)[0],
                                         "name": nm_, "osm_substation_tag": "transmission", "type": "substation"}
                                        for b_, v_, x_, y_, nm_ in ADD_BUSES]).set_index("bus")])
lines["commissioned"] = ""
lines = pd.concat([lines, pd.DataFrame(
    [{"bus0": a_, "bus1": b_, "v_nom": 500, "num_parallel": c_, "length_km": l_, "length_eq_km": l_, "inferred": False,
      "osm_ways": "S19 (not in OSM)", "name": nm_, "commissioned": d_} for a_, b_, c_, l_, d_, nm_ in ADD_LINES],
    index=[f"LX{i}" for i in range(len(ADD_LINES))])])
trafos["commissioned"] = ""
trafos = pd.concat([trafos, pd.DataFrame([{"bus0": a_, "bus1": b_, "v0": 500, "v1": 220, "inferred": False,
                                           "commissioned": d_} for a_, b_, d_ in ADD_TRAFOS])], ignore_index=True)
assert buses.index.is_unique and set(lines.bus0) | set(lines.bus1) <= set(buses.index)
note(f"added (S19, not in OSM): {len(ADD_BUSES)} buses, {len(ADD_LINES)} lines "
     f"({sum(c_ * l_ for _, _, c_, l_, _, _ in ADD_LINES):.0f} circuit-km), {len(ADD_TRAFOS)} transformers")
xy = gpd.GeoSeries(gpd.points_from_xy(buses.x, buses.y), crs=4326).to_crs(UTM)
buses["ux"], buses["uy"] = xy.x.values, xy.y.values
buses["plant_yard"] = buses.name.fillna("").str.contains(PLANT_RE, case=False, regex=True)
# OSM often maps the HV and LV yards of one substation as separate objects -> couple a substation without
# step-down transformer to the nearest lower-voltage non-junction bus within COUPLE_KM (flagged inferred)
for hv, lv in [(500, 220), (220, 110)]:
    have = set(trafos[trafos.v0 == hv].bus0)
    s_ = buses[(buses.v_nom == hv) & (buses.type == "substation") & ~buses.index.isin(have) & ~buses.plant_yard]
    c_ = buses[(buses.v_nom == lv) & (buses.type != "junction")]
    d, i = cKDTree(c_[["ux", "uy"]].values).query(s_[["ux", "uy"]].values)
    ok = d / 1e3 <= COUPLE_KM
    trafos = pd.concat([trafos, pd.DataFrame({"bus0": s_.index[ok], "bus1": c_.index[i[ok]], "v0": hv, "v1": lv,
                                              "inferred": True})], ignore_index=True)
    note(f"{hv}/{lv} kV: {ok.sum()} inferred couplings (<= {COUPLE_KM} km) for {len(s_)} uncoupled substations")
trafos.index = "T" + trafos.bus0 + "-" + trafos.bus1

G = nx.Graph()
G.add_nodes_from(buses.index)
G.add_edges_from(zip(lines.bus0, lines.bus1))
G.add_edges_from(zip(trafos.bus0, trafos.bus1))
main = max(nx.connected_components(G), key=len)
note(f"main island {len(main)}/{len(buses)} buses; others dropped")
buses = buses.loc[sorted(main)]
lines = lines[lines.bus0.isin(main) & lines.bus1.isin(main)]
trafos = trafos[trafos.bus0.isin(main) & trafos.bus1.isin(main)]

n = pypsa.Network()
n.set_snapshots(pd.date_range(f"{YEAR}-01-01", f"{YEAR}-12-31 23:00", freq="h"))  # local time UTC+7
n.add("Carrier", ["AC", "coal", "gas", "oil", "biomass", "hydro", "ror", "onwind", "solar", "solar rooftop",
                  "imports", "load shedding"])
n.add("Bus", buses.index, v_nom=buses.v_nom, x=buses.x, y=buses.y, carrier="AC")
n.buses["type_osm"] = buses.type
n.buses["name_osm"] = buses.name.fillna("")
n.buses["plant_yard"] = buses.plant_yard

# 500 kV custom type: r 0.0277, x 0.2819 ohm/km, b 4.24 uS/km (vietnamgrid paper) -> c = b/(2*pi*50);
# i_nom 2.6 kA = PyPSA standard 4-bundle Al/St 240/40 (VN 4xACSR-330 thermal ~2.9 kA; ASSUMPTION)
n.line_types.loc[LINE_TYPE[500]] = n.line_types.loc["Al/St 240/40 4-bundle 380.0"]
n.line_types.loc[LINE_TYPE[500], ["r_per_length", "x_per_length", "c_per_length", "i_nom", "f_nom"]] = \
    [0.0277, 0.2819, 4.24e-6 / (2 * np.pi * 50) * 1e9, 2.6, 50]
lt = lines.v_nom.map(LINE_TYPE)
i_nom = lt.map(n.line_types.i_nom)
n.add("Line", lines.index, bus0=lines.bus0, bus1=lines.bus1, type=lt, length=lines.length_eq_km,
      num_parallel=lines.num_parallel, s_nom=np.sqrt(3) * i_nom * lines.v_nom * lines.num_parallel, carrier="AC")
n.lines["inferred"] = lines.inferred.astype(bool)
n.lines["commissioned"] = lines.commissioned.fillna("")
# 110 kV: OSM has only ~64% of official circuit-km -> thermal limits not enforced (s_max_pu=RELAX_110);
# loading vs s_nom is still reported. 500/220 kV lines and transformers keep s_max_pu=1
n.lines.loc[n.lines.bus0.map(n.buses.v_nom) == 110, "s_max_pu"] = RELAX_110
# transformer s_nom: per-substation MVA where compiled (substation_mva.py: EVN/EVNNPT sources, OSM ratings);
# other substations share the residual of the EVN national total. Known-MVA transformers are binding
# (s_max_pu=1); unknown ones are not enforced (s_max_pu=RELAX_110), loading vs residual rating is reported.
mv = match_mva(buses)
for (v0, v1), mva in TRAFO_MVA.items():
    t = trafos[(trafos.v0 == v0) & (trafos.v1 == v1)].copy()
    off = t.bus0.map(mv.status).eq("off")  # not in service end-2024 / switchyard without step-down transformer
    if off.any():
        note(f"transformers {v0}/{v1} dropped (off in 2024 or none): {list(t[off].bus0.map(buses.name))}")
    t = t[~off]
    t["mva"] = t.bus0.map(mv.mva) / t.groupby("bus0").bus0.transform("size")  # HV bus coupled to >1 LV bus
    t["src"] = t.bus0.map(mv.source).fillna("")
    known = t.mva.notna()
    # residual of the EVN national total over substations without a compiled MVA (S2 p8); floor = smallest standard
    # unit (500/220: 450 MVA, 220/110: 125 MVA) so the model total matches EVN unless the floor binds
    resid = max(max(mva - t.mva.sum(), 0) / max((~known).sum(), 1), 450 if v0 == 500 else 125)
    n.add("Transformer", t.index, bus0=t.bus0, bus1=t.bus1, s_nom=t.mva.fillna(resid), x=0.12, r=0.003)
    n.transformers.loc[t.index, "mva_known"] = known
    n.transformers.loc[t.index, "mva_source"] = t.src
    note(f"transformers {v0}/{v1}: {len(t)}; substation MVA known {known.sum()} ({t.mva.sum():.0f} MVA); "
         f"others {(~known).sum()} x {resid:.0f} MVA (residual of EVN total {mva} MVA)")
n.transformers["inferred"] = trafos.inferred.reindex(n.transformers.index).astype(bool)
n.transformers["commissioned"] = trafos.commissioned.reindex(n.transformers.index).fillna("")
n.transformers["mva_known"] = n.transformers.mva_known.astype(bool)
hv = n.transformers.bus0.map(n.buses.v_nom).astype(int)
enf = np.array([TRAFO_ENFORCE.get((v0, 220 if v0 == 500 else 110), False) for v0 in hv])
n.transformers["s_max_pu"] = np.where(n.transformers.mva_known & enf, 1.0, RELAX_110)

# connected branch capacity per bus (MVA): load caps / plant connection room
bcap = pd.Series(0.0, index=buses.index)
for c_ in [n.lines, n.transformers]:
    bcap = bcap.add(c_.s_nom.groupby(c_.bus0).sum(), fill_value=0).add(c_.s_nom.groupby(c_.bus1).sum(), fill_value=0)

prov = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json")[["NAME_1", "geometry"]].to_crs(4326)
prov["region"] = np.select([prov.NAME_1 == "HàNội", prov.NAME_1 == "HồChíMinh", prov.NAME_1.isin(CPC),
                            prov.NAME_1.isin(SPC)], ["HANOI", "HCMC", "CPC", "SPC"], "NPC")


def region_of(lon, lat, col="region"):
    """power-corporation region (col='region') or GADM province (col='NAME_1') of points."""
    pt = gpd.GeoDataFrame(geometry=gpd.points_from_xy(np.asarray(lon), np.asarray(lat)), crs=4326)
    j = gpd.sjoin(pt, prov, how="left", predicate="within")
    j = j[~j.index.duplicated()]
    miss = j[col].isna()
    if miss.any():  # coast / offshore points -> nearest province centroid
        pc = prov.to_crs(UTM).geometry.centroid
        q = pt[miss.values].to_crs(UTM).geometry
        _, ii = cKDTree(np.c_[pc.x, pc.y]).query(np.c_[q.x, q.y])
        j.loc[miss, col] = prov[col].values[ii]
    return j[col].values


def province_sales(pop_by_prov):
    """2024 commercial electricity per GADM province (MWh-share, sums to 1) from the compiled tables
    <DATA>/demand/province_sales_2024_*.csv (D-16). 2023-only -> x corporation (else national) growth;
    missing provinces -> corporation residual split by population. None if no table exists."""
    fs = sorted((DATA / "demand").glob("province_sales_2024_*.csv"))
    if not fs:
        return None, None
    t = pd.concat([pd.read_csv(f_) for f_ in fs], ignore_index=True)
    for c in ["sales_2024_mkwh", "sales_2023_mkwh"]:
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t["key"] = t.province.map(norm_name)
    tot = t[t.province.str.upper().str.startswith("TOTAL")]
    tot_corp = {r.corporation: r for r in tot.itertuples()}
    t = t[~t.province.str.upper().str.startswith("TOTAL")].drop_duplicates("key")
    g = prov.assign(key=prov.NAME_1.map(norm_name)).set_index("key")
    t = t[t.key.isin(g.index)].set_index("key")
    nat_growth = SALES_2024_TWH / SALES_2023_TWH
    out = pd.DataFrame({"NAME_1": g.NAME_1, "region": g.region, "pop": g.NAME_1.map(pop_by_prov).fillna(0)})
    out["sales"], out["basis"] = t.sales_2024_mkwh.reindex(out.index), "2024"
    for corp_, grp in out.groupby("region"):
        T = tot_corp.get(corp_)
        gr = (T.sales_2024_mkwh / T.sales_2023_mkwh) if T is not None and T.sales_2023_mkwh > 0 and \
            T.sales_2024_mkwh > 0 else nat_growth
        m23 = grp.index[grp.sales.isna() & t.sales_2023_mkwh.reindex(grp.index).notna()]
        out.loc[m23, "sales"] = t.sales_2023_mkwh.reindex(m23) * gr
        out.loc[m23, "basis"] = f"2023 x {gr:.3f}"
    for corp_, grp in out.groupby("region"):  # residual of the corporation total -> missing provinces by pop
        miss = grp.index[grp.sales.isna()]
        if not len(miss):
            continue
        T = tot_corp.get(corp_)
        corp_total = T.sales_2024_mkwh if T is not None and T.sales_2024_mkwh > 0 else \
            REGION_MVA[corp_] / sum(REGION_MVA.values()) * SALES_2024_TWH * 1e3
        resid = max(corp_total - grp.sales.sum(), 0)
        out.loc[miss, "sales"] = resid * grp.loc[miss, "pop"] / grp.loc[miss, "pop"].sum()
        out.loc[miss, "basis"] = "corp residual x pop"
    out["share"] = out.sales / out.sales.sum()
    return out.set_index("NAME_1").share, out


buses["region"] = region_of(buses.x, buses.y)


def nearest(lon, lat, kvs):
    c = buses[buses.type.isin(["substation", "line_end"]) & buses.v_nom.isin(kvs)]
    p = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(UTM)
    d, i = cKDTree(c[["ux", "uy"]].values).query(np.c_[p.x, p.y])
    return c.index[i].values, d / 1e3


# ---------------- load: 2024 hourly national profile ----------------
src = pd.read_csv(VG / "loads-p_set.csv", index_col=0, parse_dates=True).sum(axis=1).values.reshape(365, 24)
# src day 0 behaves like a Sunday (lowest weekday = 2030-labelled Tuesdays); Tet trough ~src day 47
# 2024: Jan 1 = Monday -> offset 1 keeps weekday; Tet 2024 = Feb 10 (day 40) -> offset 8 in Tet window
days = []
for i in range(366):
    off = 8 if 25 <= i <= 55 else 1
    j = i + off
    days.append(src[j if j < 365 else j - 7])
prof = pd.Series(np.concatenate(days), index=n.snapshots)
em = pd.read_csv(DATA / "validation" / "ember_vietnam_monthly_raw.csv")
em = em[em.Date.str.startswith(str(YEAR))].pivot_table(index="Date", columns="Electricity source",
                                                     values="Generation (TWh)")
em.index = pd.to_datetime(em.index).month
E_month = em["Demand"] * CALIB["energy_TWh"][0] / em["Demand"].sum() * 1e6  # MWh
m = prof.index.month
prof = prof * m.map(E_month / prof.groupby(m).sum()).values
mean_m = prof.groupby(m).transform("mean")
k = (CALIB["pmax_MW"][0] - mean_m[prof.idxmax()]) / (prof.max() - mean_m[prof.idxmax()])
for _ in range(20):  # affine stretch around monthly mean keeps monthly energy; iterate until annual max = Pmax
    p2 = mean_m + (prof - mean_m) * k
    k *= (CALIB["pmax_MW"][0] - mean_m[p2.idxmax()]) / (p2.max() - mean_m[p2.idxmax()])
prof = mean_m + (prof - mean_m) * k
note(f"load 2024: {prof.sum() / 1e6:.2f} TWh, peak {prof.max():.0f} MW at {prof.idxmax()}, min {prof.min():.0f}, "
     f"LF {prof.mean() / prof.max():.3f} (stretch k={k:.3f})")

# spatial split: WorldPop pixels -> nearest load bus, scaled to power-corporation regions
with rasterio.open(DATA / "demand" / "worldpop" / "vnm_ppp_2020_1km_Aggregated.tif") as r:
    a = r.read(1)
    rr, cc = np.where(a > 0)
    px, py = rasterio.transform.xy(r.transform, rr, cc)
    pop = a[rr, cc].astype(float)
pts = pd.DataFrame({"pop": pop, "prov": region_of(px, py, "NAME_1")})
pts["region"] = pts.prov.map(prov.set_index("NAME_1").region)
# load buses: non-plant 110 kV substations/line ends + non-plant 220 kV substations without a 110 kV side
hv_only = set(buses.index[(buses.v_nom == 220) & (buses.type == "substation")]) - set(n.transformers.bus0)
loadbus = buses[~buses.plant_yard & (((buses.v_nom == 110) & buses.type.isin(["substation", "line_end"]))
                                     | buses.index.isin(hv_only))]
pu = gpd.GeoSeries(gpd.points_from_xy(px, py), crs=4326).to_crs(UTM)
_, ii = cKDTree(loadbus[["ux", "uy"]].values).query(np.c_[pu.x, pu.y])
pts["bus"] = loadbus.index[ii]
reg_share = pd.Series(REGION_MVA) / sum(REGION_MVA.values())
ps, ps_tab = province_sales(pts.groupby("prov")["pop"].sum())
if ps is not None:  # province commercial electricity 2024 x population within province
    pts["w"] = pts["pop"] / pts.groupby("prov")["pop"].transform("sum") * pts.prov.map(ps)
    ps_tab.to_csv(OUT / "province_load_share.csv")
    note(f"load by province sales 2024: basis {ps_tab.basis.value_counts().to_dict()}; corp shares "
         f"{ps_tab.groupby('region').share.sum().round(3).to_dict()}")
else:  # fallback: power-corporation share by 110 kV transformer MVA x population
    pts["w"] = pts["pop"] / pts.groupby("region")["pop"].transform("sum") * pts.region.map(reg_share)
w = pts.groupby("bus").w.sum().reindex(loadbus.index, fill_value=0.0)
w = w / w.sum()
# cap bus peak load; excess -> uncapped buses of the same power-corporation region, pro rata (water-filling)
cap_mw = LOAD_CAP * bcap.reindex(loadbus.index)
cap_mw[loadbus.v_nom == 110] = cap_mw[loadbus.v_nom == 110].clip(upper=LOAD_CAP_110)
cap_w = cap_mw / CALIB["pmax_MW"][0]
for _ in range(100):
    over = w > cap_w * (1 + 1e-9)
    if not over.any():
        break
    for r_, idx in loadbus.groupby("region").groups.items():
        o = over[idx]
        exc = (w[idx][o] - cap_w[idx][o]).sum()
        w[o[o].index] = cap_w[o[o].index]
        free = w[idx][(~o) & (w[idx] < cap_w[idx])]
        w[free.index] += exc * free / free.sum()
note(f"load caps binding at {(w >= cap_w * (1 - 1e-6)).sum()} buses; max bus peak {w.max() * CALIB['pmax_MW'][0]:.0f} MW;"
     f" still over cap: {(w > cap_w * 1.001).sum()}")
w = w[w > 0]
note(f"load buses {len(w)} ({int((buses.v_nom[w.index] == 220).sum())} at 220 kV); regional pop share "
     f"{pts.groupby('region')['pop'].sum().div(pts['pop'].sum()).round(3).to_dict()} -> MVA share {reg_share.round(3).to_dict()}")
w.rename("weight").to_csv(OUT / "load_weights.csv")
n.add("Load", w.index, suffix=" load", bus=w.index, p_set=pd.DataFrame(np.outer(prof.values, w.values),
                                                                         index=n.snapshots, columns=w.index + " load"))
lpk = prof.max() * w  # shedding limited to the bus's own load (no virtual export)
n.add("Generator", w.index, suffix=" load shedding", bus=w.index, carrier="load shedding", p_nom=lpk.values,
      p_max_pu=pd.DataFrame(np.outer(prof.values / prof.max(), np.ones(len(w))), index=n.snapshots,
                            columns=w.index + " load shedding"), marginal_cost=VOLL)

# ---------------- plants ----------------
u = pd.read_csv(DATA / "plants" / "vn_units_gem.csv")
built = u.status.isin(["operating", "retired", "mothballed"]) & (u.start_year.isna() | (u.start_year <= YEAR))
u = u[built & (u.retired_year.isna() | (u.retired_year > YEAR))].copy()
u["tech"] = u.tech.fillna("unknown")
u.loc[u.carrier == "offwind", "carrier"] = "onwind"  # VN 'offshore' 2024 = intertidal nearshore (Mekong delta)
u.loc[(u.carrier == "solar") & (u.tech == "Assumed PV"), "carrier"] = "solar rooftop"
u.loc[u.carrier == "biomass", "tech"] = ""
p = u.groupby(["plant", "carrier", "tech"], as_index=False).agg(p_nom=("capacity_mw", "sum"), lat=("lat", "mean"),
                                                               lon=("lon", "mean"))
p["source"] = "GEM"
for name, fx in PLANT_FIX.items():
    assert (p.plant == name).sum() == 1, name
    if "p_nom" in fx:
        p.loc[p.plant == name, ["p_nom", "source"]] = [fx["p_nom"], "GEM + S18 override"]
# small hydro: residual to official hydro total, located at WB small hydro sites <=30 MW with coordinates
txt = (DATA / "external_data/energydata/small_hydro/existingsmallhydroprojects.geojson").read_text()
gj, _ = json.JSONDecoder().raw_decode(txt)
sh = pd.DataFrame([{**f["properties"], "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
                   for f in gj["features"]])
sh = sh[(sh.P_MW <= 30) & (sh.lon > 100)]  # operating + under construction in 2016 (built by 2024)
resid = CALIB["hydro_MW"][0] - p[p.carrier.isin(["hydro", "ror"])].p_nom.sum()
sh = pd.DataFrame({"plant": "smallhydro WB " + sh.ProjCode.astype(int).astype(str), "carrier": "ror", "tech": "small",
                   "p_nom": sh.P_MW / sh.P_MW.sum() * resid, "lat": sh.lat, "lon": sh.lon, "source": "WB2016 scaled"})
note(f"small hydro residual {resid:.0f} MW spread over {len(sh)} WB sites")
p = pd.concat([p, sh], ignore_index=True)
for car, key in [("onwind", "wind_MW"), ("solar", "solar_farm_MW"), ("solar rooftop", "solar_rooftop_MW")]:
    f = CALIB[key][0] / p.loc[p.carrier == car, "p_nom"].sum()
    p.loc[p.carrier == car, "p_nom"] *= f
    note(f"{car}: scaled x{f:.3f} to {CALIB[key][0]} MW ({CALIB[key][1]})")
p = p[p.lat.notna()].reset_index(drop=True)
# rooftop: regional totals from GEM 'Assumed PV' locations, within region pro rata to load
rt = p[p.carrier == "solar rooftop"]
rt_reg = rt.groupby(region_of(rt.lon, rt.lat)).p_nom.sum()
lb_reg = buses.region[w.index]
rt_bus = w * lb_reg.map(rt_reg / w.groupby(lb_reg).sum()).fillna(0)
note(f"rooftop by region MW: {rt_reg.round(0).to_dict()}")
p = pd.concat([p[p.carrier != "solar rooftop"],
               pd.DataFrame({"plant": "rooftop " + rt_bus.index, "carrier": "solar rooftop", "tech": "",
                             "p_nom": rt_bus.values, "lat": buses.y[rt_bus.index].values,
                             "lon": buses.x[rt_bus.index].values, "source": "GEM AssumedPV region x load",
                             "bus": rt_bus.index, "dist_km": 0.0})], ignore_index=True)
# other plants: largest first -> nearest bus within MAP_KM with free connection room; else most room within 2x
cand = buses[buses.type != "junction"]
room = (MAP_ROOM * bcap[cand.index]).values.copy()
tree = cKDTree(cand[["ux", "uy"]].values)
q = p[p.carrier != "solar rooftop"].sort_values("p_nom", ascending=False)
qu = gpd.GeoSeries(gpd.points_from_xy(q.lon, q.lat), crs=4326).to_crs(UTM)
for ix, pn, x_, y_ in zip(q.index, q.p_nom, qu.x, qu.y):
    d, i = tree.query([x_, y_], k=60, distance_upper_bound=2 * MAP_KM * 1e3)
    i, d = i[np.isfinite(d)], d[np.isfinite(d)]
    kv = PLANT_FIX.get(q.plant[ix], {}).get("kv")
    if kv:  # forced connection voltage
        i, d = i[cand.v_nom.values[i] == kv], d[cand.v_nom.values[i] == kv]
    fit = (room[i] >= pn) & (d <= MAP_KM * 1e3)
    big = fit & (pn >= BIG_MW) & (cand.v_nom.values[i] == 500) & (d <= BIG_KM * 1e3)
    if big.any():
        fit = big
    j = i[fit][0] if fit.any() else (i[np.argmax(room[i])] if len(i) else tree.query([x_, y_])[1])
    room[j] -= pn
    p.loc[ix, "bus"] = cand.index[j]
    p.loc[ix, "dist_km"] = np.hypot(cand.ux.iloc[j] - x_, cand.uy.iloc[j] - y_) / 1e3
note(f"plants mapped: {len(p)}, dist km median {p.dist_km.median():.1f}, >30 km: {(p.dist_km > 30).sum()} "
     f"({p[p.dist_km > 30].p_nom.sum():.0f} MW); buses with gen > room: {(room < 0).sum()} ({-room[room < 0].sum():.0f} MW)")
for name in PLANT_FIX:
    r = p[p.plant == name].iloc[0]
    note(f"override {name}: {r.p_nom:.0f} MW -> {r.bus} ({r.dist_km:.1f} km)")
p.to_csv(OUT / "plants_mapped.csv", index=False)

# thermal + biomass generators per (bus, carrier, tech)
th = p[p.carrier.isin(["coal", "gas", "oil", "biomass"])]
g = th.groupby(["bus", "carrier", "tech"], as_index=False).p_nom.sum()
g.index = g.bus + " " + g.carrier + " " + g.tech.str.replace(" ", "-")
n.add("Generator", g.index, bus=g.bus, carrier=g.carrier, p_nom=g.p_nom,
      marginal_cost=[MC[(c, t)] for c, t in zip(g.carrier, g.tech)])
# VRE (p_max_pu added later)
for car in ["onwind", "solar", "solar rooftop"]:
    v = p[p.carrier == car].groupby("bus").p_nom.sum()
    n.add("Generator", v.index, suffix=f" {car}", bus=v.index, carrier=car, p_nom=v.values, marginal_cost=0.0)
# hydro: StorageUnit with a monthly energy budget per hydro region (N / C incl. Highlands / S):
#  - national monthly total = Ember 2024 hydro generation (D-08)
#  - regional timing = mean 2015-16 monthly inflow shares per region from pypsa-vn ERA5 network (D-15)
#  - regional annual energy proportional to installed capacity (ASSUMPTION)
#  - biproportional fit (IPF), regional monthly CF <= HYDRO_CF_MAX; month totals enforced last
hours_m = pd.Series(n.snapshots.month).value_counts().sort_index()
pv = xr.open_dataset(PVN)
inf = pv.storage_units_t_inflow.to_pandas()
su_bus = pd.Series(pv.storage_units_bus.values, index=pv.storage_units_i.values)
pv_y = pd.Series(pv.buses_y.values, index=pv.buses_i.values)
t_pv = pd.to_datetime(pv.snapshots.values)
mon = inf.T.groupby(hydro_region(pv_y[su_bus[inf.columns]].values)).sum().T.groupby([t_pv.year, t_pv.month]).sum()
share = (mon / mon.groupby(level=0).transform("sum")).groupby(level=1).mean()  # 12 x region, cols sum to 1
hp = p[p.carrier.isin(["hydro", "ror"])]
cap_r = hp.groupby(hydro_region(buses.y[hp.bus].values)).p_nom.sum().reindex(share.columns).fillna(0)
E_m = em["Hydro"].reindex(range(1, 13)) * 1e6
X = share.values * cap_r.values
A_r = cap_r.values / cap_r.sum() * E_m.sum()
ub = HYDRO_CF_MAX * np.outer(hours_m.values, cap_r.values)
for _ in range(500):
    X *= (E_m.values / X.sum(1))[:, None]
    X *= (A_r / X.sum(0))[None, :]
    X = np.minimum(X, ub)
for mi in range(12):  # enforce Ember month totals: spread any deficit over regional headroom
    for _ in range(10):
        gap = E_m.values[mi] - X[mi].sum()
        head = ub[mi] - X[mi]
        if gap <= 1 or head.sum() <= 0:
            break
        X[mi] += min(gap, head.sum()) * head / head.sum()
budget = pd.DataFrame(X, index=range(1, 13), columns=share.columns)
(DATA / "hydro").mkdir(exist_ok=True)
share.to_csv(DATA / "hydro" / "inflow_share_by_region_pypsavn_2015_2016.csv")
budget.div(1e6).round(3).to_csv(DATA / "hydro" / "hydro_budget_TWh_2024_by_region.csv")
cf_rm = budget / np.outer(hours_m.values, cap_r.values)
note(f"hydro capacity by region MW {cap_r.round(0).to_dict()}; annual TWh {(budget.sum() / 1e6).round(1).to_dict()}; "
     f"month-total error vs Ember max {np.abs(budget.sum(1) - E_m).max() / 1e3:.1f} GWh")
note("hydro monthly CF by region:\n" + cf_rm.round(2).T.to_string())
for car, mh in [("hydro", 24 * 31), ("ror", 6)]:
    v = p[p.carrier == car].groupby("bus").p_nom.sum()
    rg = hydro_region(buses.y[v.index].values)
    pu = pd.DataFrame({r: n.snapshots.month.map(cf_rm[r]).values for r in cf_rm.columns}, index=n.snapshots)
    n.add("StorageUnit", v.index, suffix=f" {car}", bus=v.index, carrier=car, p_nom=v.values, max_hours=mh,
          efficiency_store=0, efficiency_dispatch=1, cyclic_state_of_charge=True,
          inflow=pd.DataFrame(pu[rg].values * v.values, index=n.snapshots, columns=v.index + f" {car}"))
n.storage_units["hydro_region"] = hydro_region(n.buses.y[n.storage_units.bus].values)
# imports: fixed monthly profile from Ember net imports
imp_pu = pd.Series(n.snapshots.month.map(em["Net imports"] * 1e6 / pd.Series(n.snapshots.month).value_counts()
                                         .sort_index() / CALIB["imports_MW"][0]).values, index=n.snapshots)
for name, (lon, lat, sh_) in IMPORTS.items():
    b, d = nearest([lon], [lat], [220])
    n.add("Generator", f"import {name}", bus=b[0], carrier="imports", p_nom=CALIB["imports_MW"][0] * sh_,
          p_max_pu=imp_pu.clip(upper=1), p_min_pu=imp_pu.clip(upper=1), marginal_cost=0.0)
    note(f"import {name} -> {b[0]} ({buses.name.get(b[0])}) {d[0]:.0f} km")

n.export_to_netcdf(OUT / "vn2024_base.tmp.nc")  # atomic: solve_vn.py runs may be reading the file
os.replace(OUT / "vn2024_base.tmp.nc", OUT / "vn2024_base.nc")
cap = pd.concat([n.generators.groupby("carrier").p_nom.sum(), n.storage_units.groupby("carrier").p_nom.sum()])
note("capacity MW: " + str(cap.drop("load shedding").round(0).astype(int).to_dict()))
note(f"-> {OUT / 'vn2024_base.nc'}: {len(n.buses)} buses, {len(n.lines)} lines, {len(n.transformers)} trafos, "
     f"{len(n.generators)} gens, {len(n.storage_units)} storage, {len(n.loads)} loads")
(OUT / "CALIB.txt").write_text("\n".join([f"{k}: {v[0]}  [{v[1]}]" for k, v in CALIB.items()] + [""] + log))
