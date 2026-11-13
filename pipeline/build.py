"""Build the Pit Wall DuckDB database from the raw NASCAR feeds.

    python pipeline/build.py   -> data/pitwall.duckdb

Tables: races, results, tracks. Views (the business definitions everything else uses): points_results,
driver_season, race_excitement. Definitions live in DEFINITIONS below and in the MCP server's describe_data tool.
"""
import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "pitwall.duckdb"

TRACK_TYPES = {
    "superspeedway": ["Daytona International Speedway", "Talladega Superspeedway", "Atlanta Motor Speedway"],
    "intermediate": ["Las Vegas Motor Speedway", "Kansas Speedway", "Charlotte Motor Speedway", "Texas Motor Speedway",
                     "Homestead-Miami Speedway", "Darlington Raceway", "Nashville Superspeedway", "Chicagoland Speedway",
                     "Michigan International Speedway", "Auto Club Speedway"],
    "short_track": ["Bristol Motor Speedway", "Bristol Motor Speedway Dirt", "Martinsville Speedway", "Richmond Raceway",
                    "North Wilkesboro Speedway", "Bowman Gray Stadium", "Los Angeles Memorial Coliseum", "Iowa Speedway"],
    "one_mile_flat": ["Phoenix Raceway", "New Hampshire Motor Speedway", "Dover Motor Speedway",
                      "World Wide Technology Raceway"],
    "large_flat": ["Pocono Raceway", "Indianapolis Motor Speedway"],
    "road_course": ["Autódromo Hermanos Rodríguez", "Charlotte Motor Speedway Road Course", "Chicago Street Race",
                    "Circuit of The Americas", "Indianapolis Motor Speedway Road Course", "Road America",
                    "San Diego Street Course", "Sonoma Raceway", "Watkins Glen International"],
}

DEFINITIONS = {
    "points race": "race_type_id = 1. Excludes the Clash, Daytona Duels, All-Star Race and All-Star Open "
                   "(race_type_id = 2). Every season stat (wins, top 10s, average finish) counts points races only.",
    "win": "finishing_position = 1 in a points race.",
    "top 5 / top 10": "finishing_position <= 5 / <= 10 in a points race.",
    "pole": "starting_position = 1 in a points race (includes poles set by metric when qualifying is canceled).",
    "DNF": "a points-race finish whose finishing_status is not 'Running' (Accident, Engine, DVP and other "
           "mechanical or damage reasons). A blank status is treated as unknown, not a DNF.",
    "laps led": "laps_led summed over points races.",
    "average finish": "mean finishing_position over points races started.",
    "track type": "one of superspeedway (Daytona, Talladega, and Atlanta since its 2022 drafting reconfiguration), "
                  "intermediate, short_track, one_mile_flat, large_flat, road_course (includes street courses). "
                  "A documented judgment call; see the tracks table.",
    "margin of victory": "seconds between first and second at the finish; null when the feed gives none.",
    "season": "race_season; 2022-2026 are the Next Gen car's first five seasons.",
}


def parse_mov(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    races, results = [], []
    for f in sorted((RAW / "weekend").glob("*.json")):
        w = json.loads(f.read_text()).get("weekend_race") or []
        if not w:
            continue
        r = w[0]
        races.append({
            "race_id": r["race_id"], "season": r["race_season"], "race_name": r["race_name"],
            "race_type_id": r["race_type_id"], "track_id": r["track_id"], "track_name": r["track_name"],
            "race_date": pd.to_datetime(r["race_date"]).date(), "scheduled_laps": r["scheduled_laps"],
            "actual_laps": r["actual_laps"], "cars": r["number_of_cars_in_field"],
            "lead_changes": r["number_of_lead_changes"], "leaders": r["number_of_leaders"],
            "cautions": r["number_of_cautions"], "caution_laps": r["number_of_caution_laps"],
            "margin_of_victory": parse_mov(r.get("margin_of_victory")), "average_speed": r["average_speed"],
            "playoff_round": r.get("playoff_round") or 0, "tv": r.get("television_broadcaster"),
        })
        for x in r["results"]:
            results.append({
                "race_id": r["race_id"], "season": r["race_season"], "driver_id": x["driver_id"],
                "driver": x["driver_fullname"].strip(), "car_number": x["car_number"], "team": x["team_name"],
                "make": x["car_make"], "crew_chief": x.get("crew_chief_fullname"),
                "start_pos": x["starting_position"], "finish_pos": x["finishing_position"],
                "laps_led": x["laps_led"], "laps_completed": x["laps_completed"],
                "status": x["finishing_status"], "points": x["points_earned"],
                "playoff_points": x["playoff_points_earned"], "disqualified": bool(x.get("disqualified")),
            })
    tracks = [{"track_name": t, "track_type": k} for k, v in TRACK_TYPES.items() for t in v]
    rdf, xdf, tdf = pd.DataFrame(races), pd.DataFrame(results), pd.DataFrame(tracks)
    missing = sorted(set(rdf.track_name) - set(tdf.track_name))
    assert not missing, f"tracks without a type: {missing}"

    DB.unlink(missing_ok=True)
    con = duckdb.connect(str(DB))
    for name, df in (("races", rdf), ("results", xdf), ("tracks", tdf)):
        con.register("df", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df")
        con.unregister("df")
    con.execute((ROOT / "sql" / "views.sql").read_text())
    con.register("defs", pd.DataFrame(DEFINITIONS.items(), columns=["term", "definition"]))
    con.execute("CREATE TABLE definitions AS SELECT * FROM defs")

    checks = {
        "races": con.execute("SELECT count(*) FROM races").fetchone()[0],
        "points_races": con.execute("SELECT count(*) FROM races WHERE race_type_id = 1").fetchone()[0],
        "results_rows": con.execute("SELECT count(*) FROM results").fetchone()[0],
        "one_winner_per_race": con.execute(
            "SELECT count(*) FROM (SELECT race_id, sum((finish_pos = 1)::INT) w FROM results GROUP BY 1) WHERE w <> 1"
        ).fetchone()[0] == 0,
        "duplicate_driver_rows": con.execute(
            "SELECT count(*) FROM (SELECT race_id, driver_id, count(*) n FROM results GROUP BY ALL) WHERE n > 1"
        ).fetchone()[0],
        "points_races_per_season": dict(con.execute(
            "SELECT season, count(*) FROM races WHERE race_type_id = 1 GROUP BY 1 ORDER BY 1").fetchall()),
    }
    (ROOT / "data" / "build_checks.json").write_text(json.dumps(checks, indent=1, default=str))
    print(json.dumps(checks, indent=1, default=str))


if __name__ == "__main__":
    main()
