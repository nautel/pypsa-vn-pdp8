#!/usr/bin/env python3
"""Map of the VN 2024 PyPSA model: grid by voltage + small multiples of generation by type and peak load.

Run: python workflow/scripts/plot_network.py  ->  <DATA>/figures/vn_grid_model_2024.png
"""
import os
from pathlib import Path

import pyproj

os.environ.setdefault("PROJ_DATA", pyproj.datadir.get_data_dir())
import logging  # noqa: E402

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pypsa  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data"))
OUT = DATA / "figures"
OUT.mkdir(exist_ok=True)

# palette (dataviz reference instance, light): slots 1-2 validated; 110 kV as recessive neutral context
SURF, INK, INK2, MUTED, LAND, EDGE = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#f0efec", "#d4d3cf"
C500, C220, C110 = "#2a78d6", "#eb6834", "#b9b8b3"
GEN, LOAD = "#2a78d6", "#eb6834"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.edgecolor": EDGE,
                     "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED})

n = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
p = pd.read_csv(DATA / "networks" / "plants_mapped.csv")
vn = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json")
b = n.buses
v = n.lines.bus0.map(b.v_nom)

fig = plt.figure(figsize=(16, 12.5), facecolor=SURF)
gs = fig.add_gridspec(3, 4, width_ratios=[1.35, 1.35, 1, 1], wspace=0.04, hspace=0.12,
                      left=0.02, right=0.99, top=0.93, bottom=0.03)
fig.text(0.02, 0.965, "Mô hình lưới điện Việt Nam 2024 (PyPSA)", fontsize=17, weight="bold")
fig.text(0.02, 0.945, "Lưới 500/220/110 kV từ OSM; nguồn hiệu chỉnh theo số chính thức cuối 2024 (EVN, Cục Điện lực); "
         "phụ tải 308,7 TWh, Pmax 49.533 MW", fontsize=10, color=INK2)


def base(ax, ext=(101.8, 112.6, 8.2, 23.6)):
    ax.set_facecolor(SURF)
    vn.plot(ax=ax, color=LAND, edgecolor=EDGE, linewidth=0.3)
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    ax.set_aspect(1 / np.cos(np.radians(16)))
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    for s in ax.spines.values():
        s.set_visible(False)


# ---------- main map: grid ----------
ax = fig.add_subplot(gs[:, :2])
base(ax)
for kv, col, lw, z in [(110, C110, 0.5, 1), (220, C220, 1.0, 2), (500, C500, 2.0, 3)]:
    for inferred, ls in [(False, "solid"), (True, (0, (2, 2)))]:
        li = n.lines[(v == kv) & (n.lines.inferred == inferred)]
        segs = np.stack([b.loc[li.bus0, ["x", "y"]].values, b.loc[li.bus1, ["x", "y"]].values], axis=1)
        ax.add_collection(LineCollection(segs, colors=col, linewidths=lw, linestyles=ls, zorder=z,
                                         capstyle="round"))
sub = b[(b.type_osm == "substation") & b.v_nom.isin([500, 220])]
for kv, col, ms in [(220, C220, 9), (500, C500, 22)]:
    s = sub[sub.v_nom == kv]
    ax.scatter(s.x, s.y, s=ms, color=col, edgecolor=SURF, linewidth=0.8, zorder=4 + (kv == 500))
for name, x, y, dx, ha in [("Hà Nội", 105.85, 21.03, -0.25, "right"), ("Đà Nẵng", 108.2, 16.05, 0.25, "left"),
                           ("TP. Hồ Chí Minh", 106.7, 10.78, 0.9, "left")]:
    ax.annotate(name, (x, y), (x + dx, y), fontsize=10, color=INK, ha=ha, va="center", weight="bold", zorder=6)
leg = [Line2D([], [], color=C500, lw=2.0, marker="o", ms=5, mec=SURF, label="500 kV"),
       Line2D([], [], color=C220, lw=1.0, marker="o", ms=3.5, mec=SURF, label="220 kV"),
       Line2D([], [], color=C110, lw=0.8, label="110 kV"),
       Line2D([], [], color=INK2, lw=1.0, ls=(0, (2, 2)), label="nối suy luận (OSM thiếu)")]
ax.legend(handles=leg, loc="lower right", bbox_to_anchor=(1.0, 0.03), frameon=False, fontsize=10,
          title="Đường dây / trạm", title_fontsize=10, alignment="left")

# summary panel (in the East Sea area)


def vnum(x, d=0):  # Vietnamese number format: '.' thousands, ',' decimals
    return f"{x:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


ckm = {kv: (pd.read_csv(DATA / "grid" / "topology" / "lines.csv").query("v_nom == @kv")
            .eval("length_km * num_parallel").sum()) for kv in [500, 220, 110]}
off = {500: 11752, 220: 20478, 110: 23725}
cap = pd.concat([n.generators.groupby("carrier").p_nom.sum(), n.storage_units.groupby("carrier").p_nom.sum()])
rows = [("Bus", vnum(len(b))), ("Đường dây", vnum(len(n.lines))), ("Máy biến áp", vnum(len(n.transformers))),
        ("Điểm phụ tải", vnum(len(n.loads)))]
rows += [(f"km mạch {kv} kV", f"{vnum(ckm[kv])} / {vnum(off[kv])} · {ckm[kv] / off[kv] * 100:.0f}%")
         for kv in [500, 220, 110]]
gw = lambda c: vnum(cap.reindex(c).sum() / 1e3, 1) + " GW"  # noqa: E731
rows += [("Than", gw(["coal"])), ("Khí + dầu", gw(["gas", "oil"])), ("Thủy điện (gồm nhỏ)", gw(["hydro", "ror"])),
         ("Gió", gw(["onwind"])), ("Mặt trời trang trại", gw(["solar"])), ("Mặt trời mái nhà", gw(["solar rooftop"])),
         ("Sinh khối + nhập khẩu", gw(["biomass", "imports"]))]
X0, X1, y0, dy = 0.585, 0.995, 0.975, 0.0205
ax.text(X0, y0, "Tóm tắt mô hình", transform=ax.transAxes, fontsize=11, weight="bold", va="top")
ax.text(X1, y0 - 0.003, "km mạch: mô hình / EVN 2024", transform=ax.transAxes, fontsize=8, color=MUTED, va="top",
        ha="right")
for i, (k, val) in enumerate(rows):
    yy = y0 - 0.035 - i * dy
    ax.text(X0, yy, k, transform=ax.transAxes, fontsize=9, color=INK2, va="top")
    ax.text(X1, yy, val, transform=ax.transAxes, fontsize=9, color=INK, ha="right", va="top")
    if i in (3, 6):
        ax.plot([X0, X1], [yy - dy * 0.85] * 2, transform=ax.transAxes, color=EDGE, lw=0.6)

# ---------- small multiples: generation by type + peak load ----------
p["grp"] = p.carrier.map({"coal": "Than", "gas": "Khí + dầu", "oil": "Khí + dầu", "hydro": "Thủy điện",
                          "ror": "Thủy điện", "onwind": "Gió", "solar": "Mặt trời", "solar rooftop": "Mặt trời"})
peak = (n.loads_t.p_set.max()).groupby(n.loads.bus).sum()
peak = pd.DataFrame({"x": b.x[peak.index], "y": b.y[peak.index], "p_nom": peak.values})
facets = [("Than", p[p.grp == "Than"], GEN), ("Khí + dầu", p[p.grp == "Khí + dầu"], GEN),
          ("Thủy điện (gồm thủy điện nhỏ)", p[p.grp == "Thủy điện"], GEN), ("Gió", p[p.grp == "Gió"], GEN),
          ("Mặt trời (trang trại + mái nhà)", p[p.grp == "Mặt trời"], GEN), ("Phụ tải đỉnh theo nút", peak, LOAD)]
SCALE = 0.11  # marker area per MW
for k, (title, d, col) in enumerate(facets):
    a = fig.add_subplot(gs[k // 2, 2 + k % 2])
    base(a, ext=(102.0, 110.2, 8.3, 23.5))
    xx = d.lon if "lon" in d else d.x
    yy = d.lat if "lat" in d else d.y
    o = np.argsort(-d.p_nom.values)
    a.scatter(np.asarray(xx)[o], np.asarray(yy)[o], s=d.p_nom.values[o] * SCALE, color=col, alpha=0.75,
              edgecolor=SURF, linewidth=0.6, zorder=3)
    a.set_title(f"{title}\n{vnum(d.p_nom.sum() / 1e3, 1)} GW", fontsize=10, loc="left", color=INK, pad=2)
    if k == 0:  # shared size key
        for j, mw in enumerate([300, 1000, 3000]):
            a.scatter(109.0, 21.9 - j * 1.05, s=mw * SCALE, facecolor="none", edgecolor=INK2, linewidth=0.8)
            a.text(109.7, 21.9 - j * 1.05, f"{vnum(mw)} MW", va="center", fontsize=8, color=INK2)
fig.text(0.99, 0.008, "Nguồn: OSM (lưới), GEM + WB (nhà máy), EVN AR 2024-25, Cục Điện lực 1/2026, WorldPop, "
         "Ember — xem DATA_SOURCES.md", ha="right", fontsize=8, color=MUTED)
fn = OUT / "vn_grid_model_2024.png"
fig.savefig(fn, dpi=160, facecolor=SURF)
print("->", fn)
