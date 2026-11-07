#!/usr/bin/env python3
"""Corridor congestion / utilisation in solved expansion runs.
For each inter-region link: capacity, share of hours at limit (|p| >= 99 % of p_nom), mean loading, marginal value of
+1 MW (sum_t w_t |lambda_1 - lambda_0|, USD/MW/yr) vs its annualised expansion cost -> "worth expanding" / "under-used".
Note: transport model (30 regions) -> flows can never exceed limits; congestion shows up as binding hours + price spread.
Outputs: <DATA>/figures/expansion/congestion_<case>.csv, congestion_map.png
Run: RUN_TAGS=_vn,_vn_dc,_vn_hsr python expansion/congestion.py
"""
import os
import sys
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plot_vn import INK, MUTED, SEQ, SLOTS, basemap, save, vnum  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[1] / "data"))
RES = Path(os.environ.get("RES_DIR", DATA / "expansion" / "results"))  # RES_DIR/FIG_DIR: e.g. results/v2 for older runs
OUT = Path(os.environ.get("FIG_DIR", DATA / "figures" / "expansion"))
OUT.mkdir(parents=True, exist_ok=True)
TAGS = os.environ.get("RUN_TAGS", "_vn").split(",")
VAR = {"_vn": "gốc", "_vn_dc": "+ trung tâm dữ liệu", "_vn_hsr": "+ tàu cao tốc"}
LAB = {"pdp8": "QĐ VIII", "opt": "Tối ưu"}

cl = pd.read_csv(DATA / "expansion" / "clusters.csv", index_col=0)
prov = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json")
pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(cl.x, cl.y), index=cl.index, crs=4326)
j = gpd.sjoin_nearest(pts.to_crs(32648), prov[["NAME_1", "geometry"]].to_crs(32648), how="left")
cl["prov"] = j.groupby(level=0).NAME_1.first()


def analyse(nc):
    n = pypsa.Network(nc)
    w = n.snapshot_weightings.generators
    lk = n.links
    cap = lk.p_nom_opt.where(lk.p_nom_extendable, lk.p_nom)
    p = n.links_t.p0
    load = p.abs().div(cap.replace(0, np.nan), axis=1)
    lam = n.buses_t.marginal_price.clip(upper=3000)
    dl = (lam[lk.bus1].values - lam[lk.bus0].values)
    val = pd.Series((np.abs(dl) * w.values[:, None]).sum(0), index=lk.index)  # USD/MW/yr
    cc = lk.capital_cost.where(lk.capital_cost > 0)
    if cc.isna().all():  # fixed (pdp8) network: recompute expansion cost per usable MW from the cost table
        cc = None
    d = pd.DataFrame({"from": lk.bus0.map(cl.prov) + " (" + lk.bus0 + ")", "to": lk.bus1.map(cl.prov) + " (" + lk.bus1 + ")",
                      "type": lk.carrier, "km": lk.length.round(0), "cap_MW": cap.round(0),
                      "hours_at_limit_pct": (100 * ((load >= 0.99).mul(w, axis=0).sum() / w.sum())).round(1),
                      # binding = at limit AND price spread >= 1 USD/MWh (a full but non-binding link is degenerate)
                      "hours_binding_pct": (100 * (((load >= 0.99) & (np.abs(dl) >= 1)).mul(w, axis=0).sum() / w.sum())).round(1),
                      "max_flow_MW": p.abs().max().round(0),
                      "mean_loading_pct": (100 * load.mul(w, axis=0).sum() / w.sum()).round(1),
                      "max_loading_pct": (100 * load.max()).round(1),
                      "value_USD_per_MW_yr": val.round(0)})
    d = d[d.cap_MW >= 1]
    return n, d


def ann_cost_ac(km, year):
    c = pd.read_csv(Path(__file__).resolve().parent / f"costs_{year}.csv").set_index("tech").loc["HVAC_line"]
    r = 0.08
    return km * c.capex_usd_kw / 0.7 * (r / (1 - (1 + r) ** -c.life) + c.fom_pct / 100)


cases = [(t, y, s) for t in TAGS for y in [2035, 2040] for s in ["pdp8", "opt"] if (RES / f"{y}_{s}{t}.nc").exists()]
res = {}
for t, y, s in cases:
    n, d = analyse(RES / f"{y}_{s}{t}.nc")
    d["expansion_cost_USD_per_MW_yr"] = ann_cost_ac(d.km, y).where(d.type == "AC").round(0)
    d["verdict"] = np.select([(d.type == "AC") & (d.value_USD_per_MW_yr > d.expansion_cost_USD_per_MW_yr),
                              d.max_loading_pct < 50], ["nên mở rộng (giá trị > chi phí)", "dùng < 50% (dư)"], "")
    d = d.sort_values(["hours_binding_pct", "value_USD_per_MW_yr"], ascending=False)
    d.to_csv(OUT / f"congestion_{y}_{s}{t}.csv")
    res[(t, y, s)] = (n, d)
    print(f"\n=== {y} {LAB[s]} {VAR.get(t, t)}: {len(d)} links; at limit >=10% of hours: "
          f"{(d.hours_at_limit_pct >= 10).sum()}; binding >=5% of hours: {(d.hours_binding_pct >= 5).sum()}; "
          f"under-used (<50% max): {(d.max_loading_pct < 50).sum()}")
    print(d.head(8)[["from", "to", "type", "cap_MW", "hours_at_limit_pct", "hours_binding_pct", "mean_loading_pct",
                     "value_USD_per_MW_yr", "expansion_cost_USD_per_MW_yr", "verdict"]].to_string())

# ---- PDP8: inter-region capacity added by Decision 1509 but never used in the model year ----
cor = pd.read_csv(DATA / "expansion" / "corridors.csv", index_col=0)
rows = []
for (t, y, s), (n, d) in res.items():
    if s != "pdp8":
        continue
    c = pd.read_csv(Path(__file__).resolve().parent / f"costs_{y}.csv").set_index("tech").loc["HVAC_line", "capex_usd_kw"]
    a = d[d.type == "AC"].copy()
    a["exist_MW"] = (cor.mw.reindex(a.index.str[3:]).fillna(0) * 0.7).values
    a["added_MW"] = (a.cap_MW - a.exist_MW).clip(lower=0)
    a["used_added_MW"] = (a.max_flow_MW - a.exist_MW).clip(lower=0).clip(upper=a.added_MW)
    a["unused_added_MW"] = a.added_MW - a.used_added_MW
    unused_bn = float((a.unused_added_MW / 0.7 * a.km).sum() * c / 1e9)
    added_bn = float((a.added_MW / 0.7 * a.km).sum() * c / 1e9)
    rows.append({"case": f"{y} {VAR.get(t, t)}", "AC added GW": a.added_MW.sum() / 1e3,
                 "never used GW": a.unused_added_MW.sum() / 1e3, "added bn USD": added_bn, "never used bn USD": unused_bn,
                 "corridors fully unused": int(((a.added_MW > 100) & (a.used_added_MW < 1)).sum()),
                 "corridors with additions": int((a.added_MW > 100).sum())})
    a.sort_values("unused_added_MW", ascending=False).to_csv(OUT / f"pdp8_unused_additions_{y}{t}.csv")
U = pd.DataFrame(rows).round(2)
U.to_csv(OUT / "pdp8_unused_additions_summary.csv", index=False)
print("\n--- QĐ 1509 inter-region additions (model years), overnight line cost only\n" + U.to_string(index=False))

# ---- map: share of hours at limit, small multiples over available cases ----
show = [k for k in res if k[2] == "pdp8"] or list(res)
show = show[:6]
ncol = 3
nrow = int(np.ceil(len(show) / ncol))
fig, axs = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 7.6 * nrow), squeeze=False)
norm = Normalize(0, 20)
for ax, k in zip(axs.flat, show):
    n, d = res[k]
    basemap(ax)
    b = n.buses
    for i, r in d.iterrows():
        x0, y0, x1, y1 = b.x[n.links.bus0[i]], b.y[n.links.bus0[i]], b.x[n.links.bus1[i]], b.y[n.links.bus1[i]]
        col = SEQ(norm(r.hours_binding_pct)) if r.hours_binding_pct >= 1 else MUTED
        ls = (0, (4, 2)) if r.type == "DC" else "-"
        ax.plot([x0, x1], [y0, y1], color=col, lw=max(0.8, min(r.cap_MW / 2500, 6)), ls=ls, solid_capstyle="round",
                zorder=3 if r.hours_binding_pct >= 1 else 2)
    top = d[d.hours_binding_pct >= 5]
    ax.set_title(f"{LAB[k[2]]} {k[1]} {VAR.get(k[0], k[0])}\n{len(top)} hành lang nghẽn ≥5% số giờ",
                 loc="left", fontsize=10)
for ax in list(axs.flat)[len(show):]:
    ax.axis("off")
sm = plt.cm.ScalarMappable(norm=norm, cmap=SEQ)
cb = fig.colorbar(sm, ax=axs, shrink=0.5, pad=0.02)
cb.set_label("% số giờ nghẽn (hết công suất và chênh giá ≥1 USD/MWh; xám: <1%)", color=INK)
fig.text(0.01, 0.005, "Mô hình 30 vùng (truyền tải dạng vận chuyển): dòng không thể vượt giới hạn; 'đầy tải' = ràng buộc "
         "có hiệu lực. Nét đứt = HVDC. Độ dày ~ công suất.", fontsize=8.5, color=INK)
save(fig, OUT, "congestion_map")
