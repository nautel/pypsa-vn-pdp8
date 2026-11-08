#!/usr/bin/env python3
"""Parse planned transmission projects from Decision 1509/QD-BCT (30/5/2025), the MOIT implementation plan of the
revised PDP8 (Decision 768/QD-TTg), Appendix II.2 (S10 in docs/data_sources.md).

Input : <DATA>/plans/qd1509_bct_2025_caselaw.html  (full text incl. appendices, saved from caselaw.vn)
Output: <DATA>/plans/qd1509_lines.csv, qd1509_substations.csv, qd1509_hvdc_uhv.csv
Run: python workflow/scripts/parse_qd1509.py
"""
import os
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

P = (Path(os.environ.get("VN_DATA", Path(__file__).resolve().parents[2] / "data")) / "plans")
tabs = pd.read_html(io.StringIO((P / "qd1509_bct_2025_caselaw.html").read_text(encoding="utf-8", errors="ignore")))
# Appendix II.2 table index -> (region, kV, kind); verified by headers (Bang 3..14 of Appendix II.2)
MAP = {27: ("Bắc", 500, "sub"), 28: ("Bắc", 500, "line"), 29: ("Bắc", 220, "sub"), 30: ("Bắc", 220, "line"),
       31: ("Trung", 500, "sub"), 32: ("Trung", 500, "line"), 33: ("Trung", 220, "sub"), 34: ("Trung", 220, "line"),
       35: ("Nam", 500, "sub"), 36: ("Nam", 500, "line"), 37: ("Nam", 220, "sub"), 38: ("Nam", 220, "line")}


def num(x):
    m = re.search(r"[\d.,]+", str(x))
    if not m:
        return np.nan
    s = m.group(0).replace(".", "").replace(",", ".") if re.search(r"\d\.\d{3}", m.group(0)) else m.group(0).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


lines, subs = [], []
for i, (reg, kv, kind) in MAP.items():
    d = tabs[i]
    hdr = d.iloc[0].astype(str).tolist()
    period = None
    for _, r in d.iloc[1:].iterrows():
        name = str(r.iloc[1])
        if "Giai đoạn" in name:
            period = re.search(r"\d{4}-\d{4}", name).group(0)
            continue
        note = str(r.iloc[hdr.index("Ghi chú")]) if "Ghi chú" in hdr else ""
        state = str(r.iloc[hdr.index("Nhà nước đầu tư")]).strip() == "x" if "Nhà nước đầu tư" in hdr else None
        if kind == "line":
            km = num(r.iloc[hdr.index("km")])
            circ = num(r.iloc[hdr.index("Số mạch")])
            if np.isnan(km):
                continue
            lines.append({"region": reg, "kv": kv, "period": period, "name": name, "circuits": circ, "km": km,
                          "note": note, "state_invest": state, "table": i})
        else:
            mva = num(r.iloc[2])
            if np.isnan(mva):
                continue
            subs.append({"region": reg, "kv": kv, "period": period, "name": name, "mva": mva, "note": note,
                         "new": "xây mới" in note.lower(), "state_invest": state, "table": i})
L, S = pd.DataFrame(lines), pd.DataFrame(subs)
L["new"] = L.note.str.lower().str.contains("xây mới|xây dựng mới|xd mới")
L["circuit_km"] = L.km * L.circuits
L.to_csv(P / "qd1509_lines.csv", index=False)
S.to_csv(P / "qd1509_substations.csv", index=False)
uhv = pd.concat([tabs[25].assign(src="Bảng 1 UHVDC/BtB"), tabs[26].assign(src="765-1000 kV AC option")])
uhv.to_csv(P / "qd1509_hvdc_uhv.csv", index=False)

pd.set_option("display.width", 200)
print("LINES (route km / circuit km) by kV x period:")
print(L.groupby(["kv", "period"]).agg(n=("name", "size"), route_km=("km", "sum"), circuit_km=("circuit_km", "sum"))
      .round(0).to_string())
print("\nby region (2025-2030):")
print(L[L.period == "2025-2030"].groupby(["kv", "region"]).agg(n=("name", "size"), circuit_km=("circuit_km", "sum"))
      .round(0).to_string())
print("\nSUBSTATIONS MVA by kV x period x new/upgrade:")
print(S.groupby(["kv", "period", "new"]).agg(n=("name", "size"), mva=("mva", "sum")).round(0).to_string())
print("\nlongest new 500 kV lines 2025-2030:")
print(L[(L.kv == 500) & (L.period == "2025-2030")].sort_values("circuit_km", ascending=False)
      [["region", "name", "circuits", "km", "note"]].head(12).to_string(max_colwidth=60))
