#!/usr/bin/env python3
"""Build workflow/repo_data/costs/costs_<year>.csv (2035, 2040) from the Vietnam Technology Catalogue 2026 (EAV & DEA, USD2025).
Values transcribed from the data sheets (pdftotext of the three EVN-hosted PDFs, D-20). 2035 = mean(2030, 2040);
2040 = 2040 column. Fuel prices are NOT in the catalogue -> kept from costs.csv (assumptions).
Rows not overridden here (fuels, imports, VOLL, hydro, circuit ratings) are copied from costs.csv.
Run: python workflow/scripts/costs_vntc2026.py
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parents[1] / "repo_data" / "costs"
base = pd.read_csv(HERE / "costs.csv").set_index("tech")
num = ["capex_usd_kw", "fom_pct", "life", "eff", "fuel_usd_mwhth", "vom_usd_mwh", "co2_t_mwhth"]
base[num] = base[num].astype(float)
G, ST, T = "TC2026 San xuat dien", "TC2026 Luu tru-PtX", "TC2026 Truyen tai"

# (tech): {field: (2030, 2040)}; capex USD/kW (lines: USD/MW/km), fom USD/MW/yr, vom USD/MWh, eff one-way/net
SHEETS = {
    "solar": dict(capex=(520, 400), fom=(8676, 7715), life=(32, 35), vom=(0, 0),
                  src=f"{G}: Dien mat troi mat dat, MUSD/MW_e(AC) 0.52/0.40, FOM 8676/7715 USD/MW/yr"),
    "onwind": dict(capex=(1590, 1540), fom=(35898, 34534), life=(30, 30), vom=(0, 0),
                   src=f"{G}: Dien gio tren bo - tua bin toc do gio thap, 1.59/1.54 MUSD/MW, FOM 35898/34534"),
    "offwind": dict(capex=(4300, 3690), fom=(150500, 133245), life=(30, 30), vom=(0, 0),
                    src=f"{G}: Dien gio ngoai khoi mong co dinh 4.30/3.69 MUSD/MW (incl. 15% grid connection), FOM 150500/133245"),
    "CCGT": dict(capex=(1140, 1120), fom=(41904, 41074), life=(50, 50), vom=(2.46, 2.41), eff=(0.60, 0.61),
                 src=f"{G}: Tua bin khi chu trinh hon hop 1.14/1.12 MUSD/MW, FOM 41904/41074, VOM 2.46/2.41, eff 60/61%"),
    "OCGT": dict(capex=(1010, 990), fom=(29705, 29116), life=(50, 50), vom=(4.53, 4.44), eff=(0.43, 0.45),
                 src=f"{G}: Tua bin khi chu trinh don - he thong lon 1.01/0.99 MUSD/MW, FOM 29705/29116, VOM 4.53/4.44, eff 43/45%"),
    "nuclear": dict(capex=(6000, 5500), fom=(122000, 118000), life=(60, 60), vom=(2.3, 2.2), eff=(0.38, 0.40),
                    src=f"{G}: Dien hat nhan lo lon PWR 6.0/5.5 MUSD/MW (range 2025: 5-10), FOM 122000/118000, VOM 2.3/2.2"),
    "battery_4h": dict(capex=(960, 800), fom=(9600, 8000), life=(20, 30), vom=(0, 0), eff=(0.959, 0.959),
                       src=f"{ST}: Pin Li-ion quy mo nha may 4 MWh/1 MW: 0.24/0.20 MUSD/MWh x4; RTE 92% AC; FOM row ambiguous "
                           f"-> 1%/yr (ASSUMPTION)"),
    "PHS": dict(capex=(750, 750), fom=(14960, 14910), life=(50, 50), vom=(1.4, 1.4), eff=(0.894, 0.894),
                src=f"{ST}: Thuy dien tich nang 0.75 MUSD/MW, 5 h, RTE 80%, FOM 14960/14910, VOM 1.4"),
    # transmission: USD per MW per km. 500 kV AC double circuit ACSR4x330: 0.91/0.89/0.83 MUSD/km (2030/2035/2040)
    # over 2 x 2250 MW (model circuit rating); HVDC +-800 kV 1.72/1.65 MUSD/km over 8000 MW (typical LCC bipole)
    "HVAC_line": dict(capex=(0.89e6 / 4500, 0.83e6 / 4500), fom=None, fom_pct=2.0, life=(50, 50),
                      src=f"{T}: DZ tren khong 500 kV AC mach kep ACSR4x330 0.89 (2035)/0.83 (2040) MUSD/km / (2x2250 MW); "
                          f"excl. substations; FOM 2%/yr"),
    "HVDC_line": dict(capex=(1.72e6 / 8000, 1.65e6 / 8000), fom=None, fom_pct=2.0, life=(50, 50),
                      src=f"{T}: DZ tren khong DC 800 kV 1.72 (2035)/1.65 (2040) MUSD/km / 8000 MW (ASSUMPTION rating)"),
    "HVDC_converter_pair": dict(capex=(200, 200), fom=None, fom_pct=2.0, life=(40, 40),
                                src=f"{T}: Tram DC LCC tren bo 1000-1250 MW 0.10 MUSD/MW per station (2035/2040) x2"),
}
EXTRA = {"PHS_max_hours": (5, f"{ST}: thuy dien tich nang thoi gian luu tru 5 h (reservoir 6000 MWh / 1200 MW)")}

for year in [2035, 2040]:
    c = base.copy()
    for t, d in SHEETS.items():
        def pick(v, t=t):
            return (v[0] + v[1]) / 2 if year == 2035 else v[1]
        cap = pick(d["capex"])
        if t in ("HVAC_line", "HVDC_line"):  # tuple = (2035, 2040) values read directly from the sheet
            cap = d["capex"][0] if year == 2035 else d["capex"][1]
        c.loc[t, "capex_usd_kw"] = round(cap, 1)
        c.loc[t, "fom_pct"] = round(pick(d["fom"]) / (cap * 1e3) * 100, 2) if d.get("fom") else d["fom_pct"]
        c.loc[t, "life"] = pick(d["life"])
        if "vom" in d:
            c.loc[t, "vom_usd_mwh"] = round(pick(d["vom"]), 2)
        if "eff" in d:
            c.loc[t, "eff"] = round(pick(d["eff"]), 3)
        c.loc[t, "source"] = d["src"] + (" [2035=mean(2030,2040)]" if year == 2035 else " [2040 column]")
    for k, (v, s) in EXTRA.items():
        c.loc[k] = 0
        c.loc[k, ["vom_usd_mwh", "source"]] = [v, s + " (value in vom column)"]
    out = HERE / f"costs_{year}.csv"
    c.reset_index().to_csv(out, index=False)
    print(out.name)
    print(c.loc[list(SHEETS), ["capex_usd_kw", "fom_pct", "life", "eff", "vom_usd_mwh"]].to_string())
