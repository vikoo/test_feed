"""Result corrections from the official sources, per session (port of mz-ops scripts/fix_2026_from_official.py,
the script that produced the audited 2026 data, plus points).

Sources of truth: the MotoGP API classification of the final session part, gated for Sprint and Race by the
official FIM Classification PDF:
- time and laps: the API value, written only when the PDF agrees (Sprint/Race); practice and qualifying use
  the API best lap. Catches values that changed after ingest (penalties, truncated provisional times).
- order: the PDF order for Sprint and Race, classified riders first, then the non-classified riders in the
  order the PDF lists them (the API orders them differently).
- dnf: set when the PDF lists the rider as not classified.
- points (not in the original script): the PDF points when the API agrees. Catches post-race penalties.

Anything where the sources disagree is held (reported, not written), never guessed.
"""
import re

NATIONS = ("SPA|ITA|FRA|AUS|GBR|GER|JPN|TUR|RSA|BRA|POR|THA|ARG|INA|MAL|QAT|USA|AUT|CZE|NED|HUN|RSM|SUI|BEL|FIN|"
           "MEX|COL|AND|VEN|CAN|IND|KOR|CHN|NZL")
# pos, points (half points in a shortened race: 12.5), number, name
_ROW = re.compile(r"^\s*(?:(\d{1,2})\s+)?(?:(\d{1,2}(?:\.5)?)\s+)?(\d{1,2})\s+([^\d\s][^\d]*?)\s{2,}")
_ROW2 = re.compile(r"^\s*(?:(\d{1,2})\s+)?(?:(\d{1,2}(?:\.5)?)\s+)?(\d{1,2})\s+([^\d\s]\S*(?:\s+[^\d\s]\S*)*?)\s+(?:%s)\s" % NATIONS)

# Strapi session type -> predicate on an API session
SESSION_MAP = {
    "FP1": lambda s: s["type"] == "FP" and s.get("number") == 1,
    "PRACTICE": lambda s: s["type"] == "PR",
    "FP2": lambda s: s["type"] == "FP" and s.get("number") == 2,
    "QNR1": lambda s: s["type"] == "Q" and s.get("number") == 1,
    "QNR2": lambda s: s["type"] == "Q" and s.get("number") == 2,
    "Sprint": lambda s: s["type"] == "SPR",
    "Race": lambda s: s["type"] == "RAC",
}


def ms(t):
    """'1:42.811' / '01:42.811' / "1'42.811" / '41:31.467' -> milliseconds, None if not parseable."""
    if not t or not isinstance(t, str):
        return None
    try:
        parts = t.replace(",", ".").replace("'", ":").split(":")
        sec = float(parts[-1])
        mins = int(parts[-2]) if len(parts) > 1 else 0
        hrs = int(parts[-3]) if len(parts) > 2 else 0
        return round(((hrs * 60 + mins) * 60 + sec) * 1000)
    except Exception:
        return None


def parse_session_pdf(text: str) -> list:
    """Rows of a Sprint/Race Classification PDF: [{pos, pts, num, name, nc, ms}] in listed order."""
    rows, nc, in_tab = [], False, False
    for ln in text.splitlines():
        if re.search(r"\bPos\s+(?:Pts\s+)?(?:#\s+)?Rider", ln):
            in_tab = True
            continue
        if any(k in ln for k in ("Not classified", "No time set", "Not started", "Disqualified", "Not finished first lap",
                                "Not on restart grid", "Not on Restart Grid")):
            nc = True
            continue
        if "Race condition" in ln:
            in_tab = False
        if not in_tab:
            continue
        m = _ROW.match(ln) or _ROW2.match(ln)
        if not m:
            continue
        pos, pts, num, name = m.groups()
        if not nc and pos is None and pts is not None:
            pos, pts = pts, None
        tm = re.search(r"(\d+'\d\d\.\d{3})", ln)
        p = float(pts) if pts else 0
        rows.append({"pos": int(pos) if (pos and not nc) else None, "pts": int(p) if p == int(p) else p,
                     "num": int(num), "name": name.strip(), "nc": nc,
                     "ms": ms(tm.group(1).replace("'", ":")) if tm else None})
    return rows


def final_api_session(sessions: list, stype: str):
    cands = [s for s in sessions if SESSION_MAP[stype](s)]
    if stype in ("Sprint", "Race"):
        cands = [s for s in cands if s.get("status") != "CANCELLED"] or cands  # an abandoned restart keeps part 1
    return max(cands, key=lambda s: s.get("number") or 1) if cands and stype in ("Sprint", "Race") else \
        (cands[0] if cands else None)


def _norm_t(t):
    return None if t in ("", None) else t


def plan_session(stype: str, cls: list, rows: list, pdf_rows: list):
    """Corrections for one session. rows: Strapi rows {id, number, position, points, laps, time, dnf}.
    Returns (changes [(row_id, field, new, why)], held [str])."""
    changes, held = [], []
    smap = {r["number"]: r for r in rows}
    is_sc = stype in ("Sprint", "Race")
    pdf_by_num = {p["num"]: p for p in pdf_rows}

    def setf(r, field, new, why):
        if r.get(field) != new:
            changes.append((r["id"], field, new, f"#{r['number']} {field} {r.get(field)!r} -> {new!r} ({why})"))
            r[field] = new

    for c in cls:
        num = c["rider"]["number"]
        r = smap.get(num)
        if not r:
            continue
        otime = _norm_t(c.get("time") if is_sc else (c.get("best_lap") or {}).get("time"))
        if is_sc:
            p = pdf_by_num.get(num)
            if p is None:
                held.append(f"#{num}: not in PDF, time left untouched")
                continue
            if (otime is not None and (p["ms"] is None or ms(otime) != p["ms"])) or (otime is None and p["ms"] is not None):
                held.append(f"#{num}: API time {otime} vs PDF {p['ms']} ms, left untouched")
                continue
        scur = _norm_t(r.get("time"))
        coarser = otime is not None and scur not in (None, "DNF") and "." in scur and "." in otime \
            and len(otime.rsplit(".", 1)[1]) < len(scur.rsplit(".", 1)[1])
        if coarser:
            held.append(f"#{num}: API time {otime} is coarser than stored {scur} (an old cached copy), left untouched")
        elif not (scur == "DNF" and otime is None) and scur != otime:
            setf(r, "time", otime, "official time")
        tl, lcur = c.get("total_laps"), r.get("laps")
        if lcur is not None and tl is not None and lcur != tl:
            setf(r, "laps", tl, "official lap count")
        if is_sc:
            p = pdf_by_num.get(num)
            api_pts = float(c.get("points") or 0)
            if p is not None and float(p["pts"]) == api_pts and float(r.get("points") or 0) != api_pts:
                setf(r, "points", p["pts"], "official points (API and PDF agree)")
            elif p is not None and float(p["pts"]) != api_pts:
                held.append(f"#{num}: points API {api_pts:g} vs PDF {p['pts']}, left untouched")

    if is_sc and pdf_rows:
        order = [p for p in pdf_rows if not p["nc"]] + [p for p in pdf_rows if p["nc"]]
        if len(order) == len(rows) and {p["num"] for p in order} == set(smap):
            for i, p in enumerate(order, start=1):
                r = smap[p["num"]]
                if r.get("position") != i:
                    setf(r, "position", i, "official PDF order")
                if p["nc"] and not r.get("dnf"):
                    setf(r, "dnf", True, "not classified in the official PDF")
        else:
            held.append(f"PDF rows {len(order)} vs Strapi {len(rows)}: order left untouched")
    return changes, held
