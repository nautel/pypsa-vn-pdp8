#!/usr/bin/env python3
"""Figures for the VN PyPSA model, modelled on PyPSA-USA's plotting workflow
(plot_network_maps.py, plot_statistics.py, plot_validation_production.py):

  inputs  (vn2024_base.nc):  capacity_map, merit_order, capacity_by_region, load_profile, hydro_budget, [cf_heatmap]
  results (solved .nc):      production_area, line_loading_map, load_shedding_map, validation_monthly,
                             validation_bar (model vs Ember 2024)

Run (env pypsa-earth):
  python plot_vn.py inputs
  python plot_vn.py results <DATA>/networks/solved/<name>.nc
Outputs: <DATA>/figures/inputs/*.png, <DATA>/figures/results/<name>/*.png
Colors: dataviz reference palette (categorical slots in fixed order, validated adjacent for stacks/pies).
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
from matplotlib.collections import LineCollection, PatchCollection  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, Patch, Wedge  # noqa: E402

logging.disable(logging.WARNING)
DATA = Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[0] / "data"))
FIG = DATA / "figures"

# ---------- style (dataviz reference instance, light mode) ----------
SURF, INK, INK2, MUTED, LAND, EDGE, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#f0efec", "#d4d3cf", "#e6e5e1"
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
# carrier groups in slot order (order = stacking / pie order -> adjacent pairs validated)
GROUPS = {"hydro": ("Thủy điện", SLOTS[0]), "coal": ("Than", SLOTS[1]), "onwind": ("Gió", SLOTS[2]),
          "solar": ("Mặt trời trang trại", SLOTS[3]), "rooftop": ("Mặt trời mái nhà", SLOTS[4]),
          "other": ("Sinh khối + nhập khẩu", SLOTS[5]), "gas": ("Khí + dầu", SLOTS[6]),
          "shed": ("Cắt tải", SLOTS[7])}
CAR2G = {"hydro": "hydro", "ror": "hydro", "coal": "coal", "onwind": "onwind", "solar": "solar",
         "solar rooftop": "rooftop", "biomass": "other", "imports": "other", "gas": "gas", "oil": "gas",
         "load shedding": "shed"}
EMBER2G = {"Hydro": "hydro", "Coal": "coal", "Wind": "onwind", "Solar": "solar+rooftop", "Net imports": "other",
           "Gas": "gas", "Other fossil": "gas"}
BLUE_RAMP = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281",
             "#0d366b"]  # sequential steps 250..700
SEQ = LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP)
HEAT = LinearSegmentedColormap.from_list("seq_blue_full", ["#cde2fb"] + BLUE_RAMP)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK, "axes.edgecolor": EDGE,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "axes.facecolor": SURF,
                     "figure.facecolor": SURF, "axes.grid": False, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False})
VN = gpd.read_file(DATA / "shapes" / "gadm41_VNM_1.json")
EXT = (101.8, 110.4, 8.2, 23.6)


# PyPSA-Eur / PyPSA-DE technology colours (pypsa-de/config/plotting.default.yaml), used for paper figures
# (PALETTE=pypsa); same colour = same technology in every figure
PYPSA_COLORS = {"Coal": "#545454", "Gas": "#e05b09", "Nuclear": "#ff8c00", "Hydro": "#298c81",
                "Imports & biomass": "#baa741", "Other": "#baa741", "Onshore wind": "#235ebc",
                "Offshore wind": "#6895dd", "Solar PV": "#f9d002", "Battery": "#ace37f", "Storage": "#ace37f",
                "Pumped hydro": "#51dbcc", "Transmission": "#70af1d", "AC": "#70af1d", "DC": "#8a1caf",
                "Load shedding": "#dd2e23"}
PALETTE = os.environ.get("PALETTE", "")


def vnum(x, d=0):
    """number format: Vietnamese (1.234,5) by default; NUMFMT=en -> English (1,234.5) for the paper figures."""
    if os.environ.get("NUMFMT") == "en":
        return f"{x:,.{d}f}"
    return f"{x:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def save(fig, out, name):
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{name}.png", dpi=150, facecolor=SURF, bbox_inches="tight")
    plt.close(fig)
    print("->", out / f"{name}.png")


def basemap(ax):
    VN.plot(ax=ax, color=LAND, edgecolor="white", linewidth=0.6)
    ax.set_xlim(EXT[0], EXT[1])
    ax.set_ylim(EXT[2], EXT[3])
    ax.set_aspect(1 / np.cos(np.radians(16)))
    ax.set_axis_off()


def lines_xy(n, idx):
    b = n.buses
    return np.stack([b.loc[n.lines.bus0[idx], ["x", "y"]].values, b.loc[n.lines.bus1[idx], ["x", "y"]].values], 1)


def pies(ax, df, scale, order):
    """df: index bus, columns groups (MW). radius = sqrt(MW * scale) degrees (same rule as PyPSA n.plot)."""
    patches = []
    for bus, row in df.iterrows():
        tot = row.sum()
        if tot <= 0:
            continue
        r, start = np.sqrt(tot * scale), 0.0
        x, y = BUS.at[bus, "x"], BUS.at[bus, "y"]
        for g in order:
            if row.get(g, 0) > 0:
                ang = 360 * row[g] / tot
                patches.append(Wedge((x, y), r, start, start + ang, facecolor=GROUPS[g][1], edgecolor=SURF,
                                     linewidth=0.3, alpha=0.9))
                start += ang
    ax.add_collection(PatchCollection(patches, match_original=True, zorder=4))


def size_legend(ax, scale, mws, loc_xy, unit="MW", color="none"):
    x, y = loc_xy
    for k, mw in enumerate(mws):
        r = np.sqrt(mw * scale)
        yy = y - k * 1.15
        ax.add_patch(Circle((x, yy), r, facecolor=color, edgecolor=INK2, linewidth=0.8, zorder=6))
        ax.text(x + 0.75, yy, f"{vnum(mw / 1000, 1) + ' GW' if mw >= 1000 else vnum(mw) + ' ' + unit}",
                va="center", fontsize=8, color=INK2)


def group_cap(n):
    g = n.generators.assign(grp=n.generators.carrier.map(CAR2G)).groupby(["bus", "grp"]).p_nom.sum()
    s = n.storage_units.assign(grp=n.storage_units.carrier.map(CAR2G)).groupby(["bus", "grp"]).p_nom.sum()
    return pd.concat([g, s]).groupby(level=[0, 1]).sum().unstack(fill_value=0)


# ====================== INPUT FIGURES ======================
def capacity_map(n, out):
    cap = group_cap(n).drop(columns=["shed"], errors="ignore")
    v = n.lines.bus0.map(n.buses.v_nom)
    fig, ax = plt.subplots(figsize=(11, 11))
    basemap(ax)
    for kv, w, col in [(110, None, EDGE), (220, 1 / 900, MUTED), (500, 1 / 900, INK2)]:
        li = n.lines.index[v == kv]
        lw = 0.4 if w is None else np.clip(n.lines.s_nom[li] * w, 0.5, 6)
        ax.add_collection(LineCollection(lines_xy(n, li), colors=col, linewidths=lw, zorder=2 + (kv == 500)))
    order = [g for g in GROUPS if g != "shed"]
    SC = 4e-5
    pies(ax, cap[order], SC, order)
    size_legend(ax, SC, [500, 2000, 5000], (111.0, 22.6))
    ax.set_xlim(EXT[0], 113.5)
    ax.add_artist(ax.legend(handles=[Line2D([], [], color=INK2, lw=2.5, label="500 kV (độ dày ~ MVA)"),
                                     Line2D([], [], color=MUTED, lw=1.0, label="220 kV"),
                                     Line2D([], [], color=EDGE, lw=0.6, label="110 kV")],
                            loc="upper left", bbox_to_anchor=(1.0, 0.70), fontsize=8.5))
    ax.legend(handles=[Patch(color=GROUPS[g][1], label=f"{GROUPS[g][0]} ({vnum(cap[g].sum() / 1e3, 1)} GW)")
                       for g in order], loc="upper left", bbox_to_anchor=(1.0, 0.52), fontsize=9,
              title="Công suất đặt cuối 2024", title_fontsize=9, alignment="left")
    ax.set_title("Công suất nguồn theo nút và lưới truyền tải", loc="left", fontsize=13, weight="bold")
    save(fig, out, "capacity_map")


def merit_order(n, out):
    g = n.generators[n.generators.carrier != "load shedding"].copy()
    s = n.storage_units.copy()
    s["marginal_cost"] = 0.0
    d = pd.concat([g[["carrier", "p_nom", "marginal_cost"]], s[["carrier", "p_nom", "marginal_cost"]]])
    d["grp"] = d.carrier.map(CAR2G)
    rank = {k: i for i, k in enumerate(GROUPS)}
    d = d.assign(r=d.grp.map(rank)).sort_values(["marginal_cost", "r"])
    x0 = d.p_nom.cumsum().shift(fill_value=0) / 1e3
    fig, ax = plt.subplots(figsize=(10, 4.5))
    hmin = 2.0  # zero-cost blocks drawn 2 USD/MWh tall to stay visible (as PyPSA-USA does)
    for (i, r), x in zip(d.iterrows(), x0):
        ax.bar(x, max(r.marginal_cost, hmin), width=r.p_nom / 1e3, align="edge", color=GROUPS[r.grp][1],
               linewidth=0)
    peak = n.loads_t.p_set.sum(axis=1).max() / 1e3
    mean = n.loads_t.p_set.sum(axis=1).mean() / 1e3
    for val, lab, yf in [(peak, f"Pmax {vnum(peak, 1)} GW", 0.62), (mean, f"tải trung bình {vnum(mean, 1)} GW", 0.52)]:
        ax.axvline(val, color=INK, lw=0.9, ls=(0, (3, 2)))
        ax.text(val, ax.get_ylim()[1] * yf, " " + lab, fontsize=8.5, va="top", color=INK,
                bbox=dict(facecolor=SURF, edgecolor="none", pad=1))
    ax.set_xlabel("Công suất lũy kế (GW)")
    ax.set_ylabel("Chi phí biên (USD/MWh)")
    ax.grid(axis="y")
    present = [k for k in GROUPS if k in set(d.grp)]
    ax.legend(handles=[Patch(color=GROUPS[k][1], label=GROUPS[k][0]) for k in present], loc="upper left", ncol=2,
              fontsize=8.5, bbox_to_anchor=(0.0, 1.0))
    ax.set_title("Đường merit order (chi phí biên nhiên liệu là GIẢ ĐỊNH, xem DATA_SOURCES.md)", loc="left",
                 fontsize=11, weight="bold")
    save(fig, out, "merit_order")


def capacity_by_region(n, out):
    sys.path.insert(0, str(Path(__file__).parent))
    reg = pd.read_csv(DATA / "networks" / "load_weights.csv", index_col=0)  # noqa: F841 (presence check)
    prov = VN.copy()
    cpc = ["QuảngBình", "QuảngTrị", "ThừaThiênHuế", "ĐàNẵng", "QuảngNam", "QuảngNgãi", "BìnhĐịnh", "PhúYên",
           "KhánhHòa", "KonTum", "GiaLai", "ĐắkLắk", "ĐắkNông"]
    spc = ["NinhThuận", "BìnhThuận", "LâmĐồng", "BìnhPhước", "TâyNinh", "BìnhDương", "ĐồngNai", "BàRịa-VũngTàu",
           "LongAn", "TiềnGiang", "BếnTre", "TràVinh", "VĩnhLong", "ĐồngTháp", "AnGiang", "KiênGiang", "CầnThơ",
           "HậuGiang", "SócTrăng", "BạcLiêu", "CàMau"]
    prov["region"] = np.select([prov.NAME_1 == "HàNội", prov.NAME_1 == "HồChíMinh", prov.NAME_1.isin(cpc),
                                prov.NAME_1.isin(spc)], ["Hà Nội", "TP.HCM", "Miền Trung (CPC)", "Miền Nam (SPC)"],
                               "Miền Bắc (NPC)")
    pt = gpd.GeoDataFrame(geometry=gpd.points_from_xy(n.buses.x, n.buses.y), index=n.buses.index, crs=4326)
    j = gpd.sjoin_nearest(pt.to_crs(32648), prov.to_crs(32648)[["region", "geometry"]])
    j = j[~j.index.duplicated()].region
    cap = group_cap(n).drop(columns=["shed"], errors="ignore")
    byr = cap.groupby(j.reindex(cap.index)).sum() / 1e3
    load = (n.loads_t.p_set.max().groupby(n.loads.bus).sum())
    pk = load.groupby(j.reindex(load.index)).sum() / 1e3 * (n.loads_t.p_set.sum(axis=1).max() / load.sum())
    order = ["Miền Bắc (NPC)", "Hà Nội", "Miền Trung (CPC)", "Miền Nam (SPC)", "TP.HCM"]
    byr = byr.reindex(order).fillna(0)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    left = np.zeros(len(byr))
    for g in [k for k in GROUPS if k in byr]:
        ax.barh(byr.index, byr[g], left=left, color=GROUPS[g][1], height=0.62, edgecolor=SURF, linewidth=1.0,
                label=GROUPS[g][0])
        left += byr[g].values
    for i, r in enumerate(byr.index):
        ax.text(left[i] + 0.3, i, f"{vnum(left[i], 1)} GW", va="center", fontsize=8.5, color=INK)
        ax.plot([pk.get(r, 0)] * 2, [i - 0.36, i + 0.36], color=INK, lw=1.6)
    ax.plot([], [], color=INK, lw=1.6, label="đỉnh phụ tải vùng (cộng không đồng thời)")
    ax.invert_yaxis()
    ax.set_xlabel("GW")
    ax.grid(axis="x")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), fontsize=8, ncol=4)
    ax.set_title("Công suất đặt theo vùng điện lực và đỉnh phụ tải", loc="left", fontsize=11, weight="bold")
    save(fig, out, "capacity_by_region")


def load_profile(n, out):
    L = n.loads_t.p_set.sum(axis=1) / 1e3
    fig, axs = plt.subplots(2, 1, figsize=(10, 6.5), gridspec_kw={"height_ratios": [1, 1.15]})
    d = L.resample("D")
    ax = axs[0]
    ax.fill_between(d.max().index, d.min(), d.max(), color=SLOTS[0], alpha=0.18, linewidth=0, label="min–max ngày")
    ax.plot(d.mean().index, d.mean(), color=SLOTS[0], lw=1.6, label="trung bình ngày")
    t = L.idxmax()
    ax.plot([t], [L.max()], "o", ms=6, color=SLOTS[0], mec=SURF)
    ax.annotate(f"Pmax {vnum(L.max() * 1e3)} MW\n{t:%d/%m %H:%M}", (t, L.max()), (10, -5), textcoords="offset points",
                fontsize=8.5, va="top")
    ax.set_ylabel("GW")
    ax.grid(axis="y")
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title(f"Phụ tải hệ thống 2024: {vnum(L.sum() / 1e3, 1)} TWh, hệ số phụ tải {vnum(L.mean() / L.max(), 2)}",
                 loc="left", fontsize=11, weight="bold")
    ax = axs[1]
    hm = L.groupby([L.index.month, L.index.hour]).mean().unstack()
    im = ax.imshow(hm.values, aspect="auto", cmap=HEAT, origin="upper")
    ax.set_yticks(range(12), [f"T{m}" for m in hm.index])
    ax.set_xticks(range(0, 24, 3), [f"{h}h" for h in range(0, 24, 3)])
    ax.set_xlabel("Giờ trong ngày (giờ Việt Nam)")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("GW trung bình")
    cb.outline.set_visible(False)
    ax.set_title("Phụ tải trung bình theo tháng × giờ", loc="left", fontsize=10)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    save(fig, out, "load_profile")


def hydro_budget(n, out):
    fn = DATA / "hydro" / "hydro_budget_TWh_2024_by_region.csv"
    if not fn.exists():
        return
    b = pd.read_csv(fn, index_col=0)
    names = {"N": "Bắc", "C": "Trung + Tây Nguyên", "S": "Nam"}
    fig, ax = plt.subplots(figsize=(9, 3.8))
    bottom = np.zeros(12)
    for k, col in zip(["N", "C", "S"], SLOTS[:3]):
        ax.bar(b.index, b[k], bottom=bottom, color=col, width=0.7, edgecolor=SURF, linewidth=1.0, label=names[k])
        bottom += b[k].values
    ax.set_xticks(range(1, 13), [f"T{m}" for m in range(1, 13)])
    ax.set_ylabel("TWh")
    ax.grid(axis="y")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title(f"Sản lượng thủy điện 2024 theo miền: tổng {vnum(b.values.sum(), 1)} TWh (tháng = Ember; "
                 "phân miền theo lưu lượng 2015–16)", loc="left", fontsize=10.5, weight="bold")
    save(fig, out, "hydro_budget")


def cf_heatmap(n, out):
    fn = DATA / "networks" / "vre_p_max_pu_2024.csv"
    if not fn.exists():
        print("skip cf_heatmap (no ERA5 profiles yet)")
        return
    pm = pd.read_csv(fn, index_col=0, parse_dates=True)
    gen = n.generators.loc[pm.columns.intersection(n.generators.index)]
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.8), sharey=True)
    for ax, car, title in zip(axs, ["solar", "solar rooftop", "onwind"], ["Mặt trời trang trại", "Mái nhà", "Gió"]):
        gi = gen.index[gen.carrier == car]
        cf = (pm[gi] * gen.p_nom[gi]).sum(axis=1) / gen.p_nom[gi].sum()
        hm = cf.groupby([cf.index.month, cf.index.hour]).mean().unstack()
        im = ax.imshow(hm.values, aspect="auto", cmap=HEAT, vmin=0, vmax=max(0.05, hm.values.max()))
        ax.set_title(f"{title}: CF năm {vnum(cf.mean(), 3)}", loc="left", fontsize=10)
        ax.set_xticks(range(0, 24, 6), [f"{h}h" for h in range(0, 24, 6)])
        for s in ax.spines.values():
            s.set_visible(False)
        cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.01)
        cb.outline.set_visible(False)
    axs[0].set_yticks(range(12), [f"T{m}" for m in range(1, 13)])
    fig.suptitle("Hệ số công suất ERA5 2024 (theo tháng × giờ, trọng số công suất)", x=0.01, ha="left",
                 fontsize=11, weight="bold")
    fig.tight_layout()
    save(fig, out, "cf_heatmap")


# ====================== RESULT FIGURES ======================
def dispatch(n):
    g = n.generators_t.p.T.groupby(n.generators.carrier.map(CAR2G)).sum().T
    s = n.storage_units_t.p.clip(lower=0).T.groupby(n.storage_units.carrier.map(CAR2G)).sum().T
    return g.add(s, fill_value=0)[[k for k in GROUPS if k in g.columns or k in s.columns]]


def production_area(n, out):
    P = dispatch(n) / 1e3
    L = n.loads_t.p_set.sum(axis=1) / 1e3
    long = len(P) > 24 * 40
    if long:
        P, L = P.resample("D").mean(), L.resample("D").mean()
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.stackplot(P.index, P.T.values, colors=[GROUPS[c][1] for c in P.columns], labels=[GROUPS[c][0] for c in P],
                 alpha=0.9, linewidth=0)
    ax.plot(L.index, L, color=INK, lw=1.2, label="Phụ tải")
    ax.set_ylabel("GW" + (" (trung bình ngày)" if long else ""))
    ax.grid(axis="y")
    h, lab = ax.get_legend_handles_labels()
    ax.legend(h[::-1], lab[::-1], loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8.5)
    ax.set_title(f"Sản xuất điện theo nguồn: {n.snapshots[0]:%d/%m} – {n.snapshots[-1]:%d/%m/%Y}", loc="left",
                 fontsize=11, weight="bold")
    ax.margins(x=0)
    save(fig, out, "production_area")


def line_loading_map(n, out):
    ld = (n.lines_t.p0.abs().mean() / n.lines.s_nom).clip(0, 1.5)
    hot = (n.lines_t.p0.abs().div(n.lines.s_nom) >= 0.99).mean()
    v = n.lines.bus0.map(n.buses.v_nom)
    fig, axs = plt.subplots(1, 2, figsize=(14, 10))
    for ax, val, title, lab in [(axs[0], ld, "Mức tải trung bình (|P|/S định mức)", "mức tải TB"),
                                (axs[1], hot, "Tỷ lệ số giờ đầy tải (≥ 99%)", "tỷ lệ giờ")]:
        basemap(ax)
        norm = Normalize(0, 1 if lab == "mức tải TB" else max(0.05, float(hot[v >= 220].max())))
        for kv, lw in [(110, 0.6), (220, 1.4), (500, 2.6)]:
            li = n.lines.index[v == kv]
            ax.add_collection(LineCollection(lines_xy(n, li), colors=SEQ(norm(val[li].values)), linewidths=lw,
                                             zorder=2 + (kv == 500)))
        sm = plt.cm.ScalarMappable(norm=norm, cmap=SEQ)
        cb = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.0, shrink=0.5)
        cb.set_label(lab)
        cb.outline.set_visible(False)
        ax.set_title(title, loc="left", fontsize=11, weight="bold")
    axs[1].legend(handles=[Line2D([], [], color=INK2, lw=w, label=f"{kv} kV") for kv, w in
                           [(500, 2.6), (220, 1.4), (110, 0.6)]], loc="lower right")
    fig.text(0.01, 0.01, "110 kV không ràng buộc nhiệt (OSM thiếu 36% chiều dài) nên có thể > 100%; "
             "500/220 kV ràng buộc theo S định mức.", fontsize=8.5, color=MUTED)
    save(fig, out, "line_loading_map")


def load_shedding_map(n, out):
    gi = n.generators.index[n.generators.carrier == "load shedding"]
    e = n.generators_t.p[gi].sum().groupby(n.generators.bus[gi]).sum() / 1e3  # GWh
    e = e[e > 0.01]
    fig, ax = plt.subplots(figsize=(8.5, 11))
    basemap(ax)
    v = n.lines.bus0.map(n.buses.v_nom)
    ax.add_collection(LineCollection(lines_xy(n, n.lines.index[v >= 220]), colors=EDGE, linewidths=0.8))
    SC = 2e-3
    ax.scatter(n.buses.x[e.index], n.buses.y[e.index], s=0, zorder=1)
    for b_, val in e.items():
        ax.add_patch(Circle((n.buses.at[b_, "x"], n.buses.at[b_, "y"]), np.sqrt(val * SC), facecolor=SLOTS[7],
                            edgecolor=SURF, linewidth=0.5, alpha=0.85, zorder=4))
    size_legend(ax, SC, [1, 10, 50], (108.6, 22.6), unit="GWh")
    tot = e.sum()
    share = tot / (n.loads_t.p_set.sum().sum() / 1e3) * 100
    ax.set_title(f"Cắt tải theo nút: {vnum(tot, 1)} GWh ({vnum(share, 2)}% điện năng)", loc="left", fontsize=12,
                 weight="bold")
    for k, (b_, val) in enumerate(e.sort_values(ascending=False).head(6).items()):
        nm = n.buses.name_osm.get(b_, "") or b_
        ax.text(0.62, 0.42 - k * 0.025, f"{nm[:34]}: {vnum(val, 1)} GWh", transform=ax.transAxes, fontsize=8,
                color=INK2)
    save(fig, out, "load_shedding_map")


def ember_monthly():
    em = pd.read_csv(DATA / "validation" / "ember_vietnam_monthly_raw.csv")
    em = em[em.Date.str.startswith("2024") & em["Electricity source"].isin(EMBER2G)]
    em["grp"] = em["Electricity source"].map(EMBER2G)
    em["m"] = pd.to_datetime(em.Date).dt.month
    return em.pivot_table(index="m", columns="grp", values="Generation (TWh)", aggfunc="sum")


def model_monthly(n):
    P = dispatch(n)
    P["solar+rooftop"] = P.pop("solar") + P.pop("rooftop") if "rooftop" in P else P.pop("solar")
    w = n.snapshot_weightings.generators
    return P.mul(w, axis=0).groupby(P.index.month).sum() / 1e6, w.groupby(n.snapshots.month).sum()


VAL = [("coal", "Than"), ("gas", "Khí + dầu"), ("hydro", "Thủy điện"), ("onwind", "Gió"),
       ("solar+rooftop", "Mặt trời (gồm mái nhà)"), ("other", "Nhập khẩu + sinh khối")]


def validation(n, out):
    mod, hrs = model_monthly(n)
    em = ember_monthly()
    hours_m = pd.Series(pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h").month).value_counts().sort_index()
    frac = (hrs / hours_m.reindex(hrs.index)).rename("frac")
    emc = em.reindex(mod.index).mul(frac, axis=0)  # Ember scaled to the hours actually simulated
    partial = (frac < 0.999).any()
    # monthly small multiples
    fig, axs = plt.subplots(2, 3, figsize=(13, 6.2), sharex=True)
    for ax, (k, title) in zip(axs.flat, VAL):
        x = np.arange(len(mod.index))
        ax.bar(x - 0.18, emc.get(k, 0), width=0.36, color=MUTED, label="Ember 2024", linewidth=0)
        ax.bar(x + 0.18, mod.get(k, 0), width=0.36, color=SLOTS[0], label="Mô hình", linewidth=0)
        ax.set_xticks(x, [f"T{m}" for m in mod.index])
        dm, de = float(mod.get(k, pd.Series(0)).sum()), float(emc.get(k, pd.Series(0)).sum())
        dev = (dm - de) / de * 100 if de else np.nan
        ax.set_title(f"{title}: {vnum(dm, 2)} vs {vnum(de, 2)} TWh ({dev:+.0f}%)", loc="left", fontsize=9.5)
        ax.grid(axis="y")
    h, lab = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, lab, loc="upper right", ncol=2, fontsize=9)
    fig.suptitle("Kiểm chứng sản lượng theo tháng: mô hình vs Ember 2024" +
                 (" (Ember nhân theo tỷ lệ số giờ đã mô phỏng)" if partial else ""), x=0.01, ha="left",
                 fontsize=11, weight="bold")
    fig.tight_layout()
    save(fig, out, "validation_monthly")
    # totals bar
    tot = pd.DataFrame({"Ember 2024": emc.sum(), "Mô hình": mod.sum()}).reindex([k for k, _ in VAL]).fillna(0)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    y = np.arange(len(tot))
    ax.barh(y - 0.19, tot["Ember 2024"], height=0.38, color=MUTED, label="Ember 2024", linewidth=0)
    ax.barh(y + 0.19, tot["Mô hình"], height=0.38, color=SLOTS[0], label="Mô hình", linewidth=0)
    for i, k in enumerate(tot.index):
        de, dm = tot.at[k, "Ember 2024"], tot.at[k, "Mô hình"]
        ax.text(max(de, dm) * 1.01 + 0.05, i, f"{(dm - de) / de * 100:+.0f}%" if de else "", va="center",
                fontsize=8.5, color=INK)
    ax.set_yticks(y, [t for _, t in VAL])
    ax.invert_yaxis()
    ax.set_xlabel("TWh")
    ax.grid(axis="x")
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title("Sản lượng theo nguồn: mô hình vs Ember 2024", loc="left", fontsize=11, weight="bold")
    save(fig, out, "validation_bar")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "inputs"
    if mode == "inputs":
        n = pypsa.Network(DATA / "networks" / "vn2024_base.nc")
        BUS = n.buses
        o = FIG / "inputs"
        for f in [capacity_map, merit_order, capacity_by_region, load_profile, hydro_budget, cf_heatmap]:
            f(n, o)
    else:
        fn = Path(sys.argv[2])
        n = pypsa.Network(fn)
        BUS = n.buses
        o = FIG / "results" / fn.stem
        for f in [production_area, line_loading_map, load_shedding_map, validation]:
            f(n, o)
