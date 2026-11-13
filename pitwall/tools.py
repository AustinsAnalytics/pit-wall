"""Pit Wall tools: plain Python functions over the DuckDB database. The MCP server (server.py) exposes these to AI
assistants; the evaluation suite (evals/) calls the same functions and checks them against trusted SQL.

Every season stat follows the business definitions in the `definitions` table (points races only, etc.).
"""
import difflib
import re
from functools import lru_cache
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parent.parent / "data" / "pitwall.duckdb"
MAX_ROWS = 500
STATS = {"wins", "top5s", "top10s", "poles", "dnfs", "laps_led", "avg_finish", "avg_start", "points", "starts"}
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|"
                       r"pragma|set|call|checkpoint|vacuum|truncate)\b", re.I)


class ToolError(ValueError):
    """A clear, user-facing error (bad input, ambiguous name, unsafe SQL)."""


@lru_cache(maxsize=1)
def _con():
    return duckdb.connect(str(DB), read_only=True)


def _rows(sql, params=()):
    cur = _con().execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


BASIS = "points races only (race_type_id = 1: excludes the Clash, Daytona Duels and All-Star races); see describe_data"


def audit_sql(sql, params=()):
    """The query behind an answer with its parameters filled in, so anyone can paste it into DuckDB and check it."""
    out, parts = [], sql.split("?")
    for i, part in enumerate(parts[:-1]):
        v = params[i]
        out.append(part + (str(v) if isinstance(v, (int, float)) else "'" + str(v).replace("'", "''") + "'"))
    out.append(parts[-1])
    return " ".join("".join(out).split())


# ------------------------------------------------------------------ data dictionary
def describe_data() -> dict:
    """Tables, columns and the business definitions every answer must follow."""
    tables = {}
    for t in ("races", "results", "tracks", "points_results", "driver_season", "race_excitement"):
        tables[t] = [f"{c[0]} ({c[1]})" for c in _con().execute(f"DESCRIBE {t}").fetchall()]
    defs = {r["term"]: r["definition"] for r in _rows("SELECT * FROM definitions")}
    types = {}
    for r in _rows("SELECT track_type, list(track_name ORDER BY track_name) AS tracks FROM tracks GROUP BY 1"):
        types[r["track_type"]] = r["tracks"]
    seasons = [r["season"] for r in _rows("SELECT DISTINCT season FROM races ORDER BY 1")]
    return {"seasons": seasons, "tables": tables, "definitions": defs, "track_types": types}


# ------------------------------------------------------------------ name resolution
def find_driver(name: str) -> dict:
    """Resolve a driver name (full, last name or close spelling) to exactly one driver, or explain the ambiguity."""
    q = name.strip().lower()
    drivers = _rows("SELECT driver_id, any_value(driver) AS driver, min(season) AS first, max(season) AS last "
                    "FROM results GROUP BY driver_id")
    exact = [d for d in drivers if d["driver"].lower() == q]
    if len(exact) == 1:
        return exact[0]
    last = [d for d in drivers if d["driver"].lower().split()[-1] == q.split()[-1]] if q else []
    if len(q.split()) == 1 and len(last) == 1:
        return last[0]
    sub = [d for d in drivers if q in d["driver"].lower()]
    if len(sub) == 1:
        return sub[0]
    cands = sub or last
    if len(cands) > 1:
        raise ToolError(f"'{name}' matches more than one driver: "
                        f"{', '.join(sorted(d['driver'] for d in cands))}. Use the full name.")
    close = difflib.get_close_matches(q, [d["driver"].lower() for d in drivers], n=3, cutoff=0.75)
    if len(close) == 1:
        return next(d for d in drivers if d["driver"].lower() == close[0])
    raise ToolError(f"No driver matches '{name}'." + (f" Did you mean: {', '.join(close)}?" if close else ""))


def find_track(name: str) -> str:
    """Resolve a track name or nickname to one track_name."""
    q = name.strip().lower()
    tracks = [r["track_name"] for r in _rows("SELECT track_name FROM tracks")]
    exact = [t for t in tracks if t.lower() == q]
    if exact:
        return exact[0]
    sub = [t for t in tracks if q in t.lower()]
    if len(sub) == 1:
        return sub[0]
    if len(sub) > 1:
        # prefer the oval when a road-course variant also matches (e.g. 'Charlotte'), but say so
        ovals = [t for t in sub if "Road Course" not in t and "Dirt" not in t]
        if len(ovals) == 1:
            return ovals[0]
        raise ToolError(f"'{name}' matches several tracks: {', '.join(sorted(sub))}.")
    close = difflib.get_close_matches(q, [t.lower() for t in tracks], n=1, cutoff=0.6)
    if close:
        return next(t for t in tracks if t.lower() == close[0])
    raise ToolError(f"No track matches '{name}'.")


# ------------------------------------------------------------------ question tools
def driver_season_stats(driver: str, season: int) -> dict:
    """A driver's points-race line for one season: starts, wins, top 5s, top 10s, poles, DNFs, laps led, averages."""
    d = find_driver(driver)
    sql, params = "SELECT * FROM driver_season WHERE driver_id = ? AND season = ?", (d["driver_id"], season)
    rows = _rows(sql, params)
    if not rows:
        raise ToolError(f"{d['driver']} made no points-race starts in {season}.")
    return {**rows[0], "basis": BASIS, "sql": audit_sql(sql, params)}


def season_leaders(season: int, stat: str = "wins", top_n: int = 10) -> list:
    """Top drivers in a season by one stat (points races only). avg_finish/avg_start rank lowest first and need 10+ starts."""
    if stat not in STATS:
        raise ToolError(f"stat must be one of {sorted(STATS)}")
    asc = stat in ("avg_finish", "avg_start")
    where = "season = ?" + (" AND starts >= 10" if asc else "")
    sql = (f"SELECT driver, {stat}, starts FROM driver_season WHERE {where} "
           f"ORDER BY {stat} {'ASC' if asc else 'DESC'}, driver LIMIT ?")
    params = (season, int(top_n))
    return {"leaders": _rows(sql, params), "basis": BASIS, "sql": audit_sql(sql, params)}


def track_history(track: str, since_season: int = 2022) -> dict:
    """Points-race winners at a track since a season, plus how competitive those races were."""
    t = find_track(track)
    sql = """SELECT season, race_date, race_name, driver AS winner, start_pos AS winner_started
             FROM points_results WHERE track_name = ? AND season >= ? AND win ORDER BY race_date"""
    winners = _rows(sql, (t, since_season))
    summary = _rows("""
        SELECT count(*) AS races, round(avg(lead_changes), 1) AS avg_lead_changes,
               round(avg(cautions), 1) AS avg_cautions, round(avg(margin_of_victory), 3) AS avg_margin_of_victory
        FROM race_excitement WHERE track_name = ? AND season >= ?""", (t, since_season))[0]
    return {"track": t, "since_season": since_season, "winners": winners, **summary, "basis": BASIS,
            "sql": audit_sql(sql, (t, since_season))}


def race_result(season: int, race: str, top_n: int = 40) -> dict:
    """Finishing order of one points race, found by track or race name (use race_date if a track hosts two races)."""
    matches = _rows("""
        SELECT DISTINCT race_id, race_name, track_name, race_date FROM points_results
        WHERE season = ? AND (lower(track_name) LIKE ? OR lower(race_name) LIKE ?) ORDER BY race_date""",
                    (season, f"%{race.lower()}%", f"%{race.lower()}%"))
    if not matches:
        raise ToolError(f"No {season} points race matches '{race}'.")
    if len(matches) > 1 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", race):
        options = "; ".join(f"{m['race_name']} ({m['race_date']})" for m in matches)
        raise ToolError(f"'{race}' matches {len(matches)} races in {season}: {options}. Ask by race name or date.")
    m = matches[0]
    sql = """SELECT finish_pos, driver, car_number, team, make, start_pos, laps_led, status
             FROM points_results WHERE race_id = ? ORDER BY finish_pos LIMIT ?"""
    params = (m["race_id"], int(top_n))
    return {"race": m["race_name"], "track": m["track_name"], "date": str(m["race_date"]), "results": _rows(sql, params),
            "sql": audit_sql(sql, params)}


def excitement_by_track_type(season: int | None = None) -> list:
    """Average lead changes, cautions and margin of victory by track type (points races), optionally for one season."""
    where, params = ("WHERE season = ?", (season,)) if season else ("", ())
    sql = f"""
        SELECT track_type, count(*) AS races, round(avg(lead_changes), 1) AS avg_lead_changes,
               round(avg(cautions), 1) AS avg_cautions, round(avg(margin_of_victory), 3) AS avg_margin_of_victory,
               round(avg((margin_of_victory < 0.1)::INT) * 100, 1) AS pct_photo_finish
        FROM race_excitement {where} GROUP BY 1 ORDER BY avg_lead_changes DESC"""
    return {"rows": _rows(sql, params), "basis": BASIS, "sql": audit_sql(sql, params)}


def run_sql(sql: str, max_rows: int = 200) -> dict:
    """Run one read-only SELECT (or WITH ... SELECT) query. Writes, multiple statements and settings are refused."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise ToolError("Only one statement is allowed.")
    if not re.match(r"^(select|with)\b", s, re.I):
        raise ToolError("Only SELECT queries (optionally starting with WITH) are allowed.")
    if FORBIDDEN.search(re.sub(r"'[^']*'", "''", s)):
        raise ToolError("The query contains a statement that is not allowed (this tool is read-only).")
    n = max(1, min(int(max_rows), MAX_ROWS))
    cur = _con().execute(f"SELECT * FROM ({s}) AS q LIMIT {n + 1}")
    cols = [d[0] for d in cur.description]
    data = cur.fetchall()
    return {"columns": cols, "rows": [list(r) for r in data[:n]], "truncated": len(data) > n, "sql": s}
