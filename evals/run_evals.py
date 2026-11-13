"""Validate every Pit Wall tool, through the real MCP protocol, against trusted SQL.

    python evals/run_evals.py     -> evals/results.json

Each question pairs a tool call with a trusted query written directly against the raw tables (not the views the tools
use), so a mistake in the shared business logic shows up as a failure. 'Trap' questions encode the ways AI answers
usually go wrong: counting exhibition races, guessing between two drivers or two races, unsafe SQL.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import duckdb
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "pitwall.duckdb"
POINTS = "JOIN races ra USING (race_id) WHERE ra.race_type_id = 1"   # trusted queries spell the definition out

Q = [
    # ---- season stats
    ("Joey Logano's points-race wins in 2024", "driver_season_stats", {"driver": "Joey Logano", "season": 2024},
     lambda r: r["wins"], f"SELECT count(*) FROM results r {POINTS} AND r.season = 2024 AND r.driver = 'Joey Logano' AND r.finish_pos = 1"),
    ("Kyle Larson's top-10 finishes in 2023", "driver_season_stats", {"driver": "Larson", "season": 2023},
     lambda r: r["top10s"], f"SELECT count(*) FROM results r {POINTS} AND r.season = 2023 AND r.driver = 'Kyle Larson' AND r.finish_pos <= 10"),
    ("Denny Hamlin's laps led in 2022", "driver_season_stats", {"driver": "Denny Hamlin", "season": 2022},
     lambda r: r["laps_led"], f"SELECT sum(r.laps_led) FROM results r {POINTS} AND r.season = 2022 AND r.driver = 'Denny Hamlin'"),
    ("Chase Elliott's average finish in 2025", "driver_season_stats", {"driver": "Chase Elliott", "season": 2025},
     lambda r: r["avg_finish"], f"SELECT round(avg(r.finish_pos), 2) FROM results r {POINTS} AND r.season = 2025 AND r.driver = 'Chase Elliott'"),
    ("Ross Chastain's DNFs in 2024", "driver_season_stats", {"driver": "Chastain", "season": 2024},
     lambda r: r["dnfs"], f"SELECT count(*) FROM results r {POINTS} AND r.season = 2024 AND r.driver = 'Ross Chastain' AND r.status NOT IN ('Running', '')"),
    ("William Byron's poles in 2025", "driver_season_stats", {"driver": "William Byron", "season": 2025},
     lambda r: r["poles"], f"SELECT count(*) FROM results r {POINTS} AND r.season = 2025 AND r.driver = 'William Byron' AND r.start_pos = 1"),
    # ---- leaderboards
    ("Most wins in 2026", "season_leaders", {"season": 2026, "stat": "wins", "top_n": 1},
     lambda r: r["leaders"][0]["driver"], f"SELECT r.driver FROM results r {POINTS} AND r.season = 2026 AND r.finish_pos = 1 GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1"),
    ("Most laps led in 2023", "season_leaders", {"season": 2023, "stat": "laps_led", "top_n": 1},
     lambda r: r["leaders"][0]["driver"], f"SELECT r.driver FROM results r {POINTS} AND r.season = 2023 GROUP BY 1 ORDER BY sum(r.laps_led) DESC LIMIT 1"),
    ("Best average finish in 2022 (10+ starts)", "season_leaders", {"season": 2022, "stat": "avg_finish", "top_n": 1},
     lambda r: r["leaders"][0]["driver"], f"SELECT r.driver FROM results r {POINTS} AND r.season = 2022 GROUP BY 1 HAVING count(*) >= 10 ORDER BY avg(r.finish_pos), 1 LIMIT 1"),
    ("Most top-5s in 2025", "season_leaders", {"season": 2025, "stat": "top5s", "top_n": 1},
     lambda r: r["leaders"][0]["top5s"], f"SELECT max(n) FROM (SELECT count(*) n FROM results r {POINTS} AND r.season = 2025 AND r.finish_pos <= 5 GROUP BY r.driver)"),
    # ---- tracks and races
    ("Daytona 500 winners, 2022-2026", "track_history", {"track": "Daytona", "since_season": 2022},
     lambda r: [w["winner"] for w in r["winners"] if w["race_name"].upper() == "DAYTONA 500"],
     f"SELECT list(r.driver ORDER BY ra.race_date) FROM results r {POINTS} AND ra.track_name = 'Daytona International Speedway' AND upper(ra.race_name) = 'DAYTONA 500' AND r.finish_pos = 1"),
    ("Different winners at Martinsville since 2022", "track_history", {"track": "Martinsville", "since_season": 2022},
     lambda r: len({w["winner"] for w in r["winners"]}),
     f"SELECT count(DISTINCT r.driver) FROM results r {POINTS} AND ra.track_name = 'Martinsville Speedway' AND r.finish_pos = 1"),
    ("Average lead changes at Talladega since 2022", "track_history", {"track": "Talladega", "since_season": 2022},
     lambda r: r["avg_lead_changes"], "SELECT round(avg(lead_changes), 1) FROM races WHERE race_type_id = 1 AND track_name = 'Talladega Superspeedway'"),
    ("Winner of the 2025 Coca-Cola 600", "race_result", {"season": 2025, "race": "Coca-Cola 600", "top_n": 1},
     lambda r: r["results"][0]["driver"], f"SELECT r.driver FROM results r {POINTS} AND ra.season = 2025 AND ra.race_name ILIKE '%Coca-Cola 600%' AND r.finish_pos = 1"),
    ("Winner of the 2026 race at Homestead-Miami", "race_result", {"season": 2026, "race": "Homestead", "top_n": 1},
     lambda r: r["results"][0]["driver"], f"SELECT r.driver FROM results r {POINTS} AND ra.season = 2026 AND ra.track_name = 'Homestead-Miami Speedway' AND r.finish_pos = 1"),
    ("Track type with the most lead changes per race", "excitement_by_track_type", {},
     lambda r: r["rows"][0]["track_type"],
     "SELECT t.track_type FROM races ra JOIN tracks t USING (track_name) WHERE ra.race_type_id = 1 GROUP BY 1 ORDER BY avg(ra.lead_changes) DESC LIMIT 1"),
    ("Photo finishes (< 0.1 s) at superspeedways, %", "excitement_by_track_type", {},
     lambda r: next(x["pct_photo_finish"] for x in r["rows"] if x["track_type"] == "superspeedway"),
     "SELECT round(avg((margin_of_victory < 0.1)::INT) * 100, 1) FROM races ra JOIN tracks t USING (track_name) WHERE ra.race_type_id = 1 AND t.track_type = 'superspeedway'"),
    ("Manufacturer with the most 2026 wins (SQL tool)", "run_sql",
     {"sql": "WITH w AS (SELECT make, count(*) AS wins FROM points_results WHERE season = 2026 AND win GROUP BY make) SELECT make FROM w ORDER BY wins DESC LIMIT 1"},
     lambda r: r["rows"][0][0], f"SELECT r.make FROM results r {POINTS} AND r.season = 2026 AND r.finish_pos = 1 GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"),
    ("Team with the most wins, 2022-2026 (SQL tool)", "run_sql",
     {"sql": "SELECT team, sum(win::INT) AS wins FROM points_results GROUP BY team ORDER BY wins DESC LIMIT 1"},
     lambda r: r["rows"][0][0], f"SELECT r.team FROM results r {POINTS} AND r.finish_pos = 1 GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"),
    # ---- traps: where AI answers usually go wrong
    ("TRAP: 'Dillon' is two drivers - must ask, not guess", "driver_season_stats", {"driver": "Dillon", "season": 2024},
     lambda r: "error" in r and "Austin Dillon" in r["error"] and "Ty Dillon" in r["error"], "SELECT true"),
    ("TRAP: exhibition wins don't count (Ryan Preece won the 2026 Clash)", "driver_season_stats", {"driver": "Ryan Preece", "season": 2026},
     lambda r: r["wins"], f"SELECT count(*) FROM results r {POINTS} AND r.season = 2026 AND r.driver = 'Ryan Preece' AND r.finish_pos = 1"),
    ("TRAP: two Talladega races in 2025 - must ask which", "race_result", {"season": 2025, "race": "Talladega"},
     lambda r: "error" in r and "2 races" in r["error"], "SELECT true"),
    ("TRAP: 'Charlotte' means the oval, not the Roval", "track_history", {"track": "Charlotte"},
     lambda r: r["track"], "SELECT 'Charlotte Motor Speedway'"),
    ("TRAP: the SQL tool refuses writes", "run_sql", {"sql": "DROP TABLE results"},
     lambda r: "error" in r, "SELECT true"),
    ("TRAP: the SQL tool refuses a second statement", "run_sql", {"sql": "SELECT 1; DELETE FROM results"},
     lambda r: "error" in r, "SELECT true"),
]


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    return a == b


async def main():
    con = duckdb.connect(str(DB), read_only=True)
    params = StdioServerParameters(command=sys.executable, args=["-m", "pitwall.server"], cwd=str(ROOT))
    out = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = sorted(t.name for t in listed.tools)
            for i, (question, tool, args, extract, gold_sql) in enumerate(Q, 1):
                t0 = time.perf_counter()
                res = await session.call_tool(tool, args)
                ms = (time.perf_counter() - t0) * 1000
                payload = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
                if isinstance(payload, dict) and set(payload) == {"result"}:
                    payload = payload["result"]
                try:
                    got = extract(payload)
                except Exception as e:  # noqa: BLE001
                    got = f"could not read answer: {e}"
                expected = con.execute(gold_sql).fetchone()[0]
                ok = same(got, expected)
                cited = payload.get("sql") if isinstance(payload, dict) else None
                reproduces = None
                if cited and "error" not in payload:
                    cur = con.execute(cited)
                    cols = [c[0] for c in cur.description]
                    rerun = [dict(zip(cols, row)) for row in cur.fetchall()]
                    rows = (payload.get("leaders") or payload.get("results") or payload.get("winners") or
                            (payload.get("rows") if isinstance(payload.get("rows"), list) and payload["rows"]
                             and isinstance(payload["rows"][0], dict) else None))
                    if rows is not None:
                        reproduces = json.dumps(rerun, default=str) == json.dumps(rows, default=str)
                    elif tool == "run_sql":
                        reproduces = [list(r.values()) for r in rerun][:len(payload["rows"])] == payload["rows"]
                    else:
                        reproduces = all(json.dumps(rerun[0].get(k), default=str) == json.dumps(v, default=str)
                                         for k, v in payload.items() if k in rerun[0])
                out.append({"id": i, "question": question, "tool": tool, "args": args, "answer": got,
                            "trusted": expected, "pass": ok, "ms": round(ms, 1), "trap": question.startswith("TRAP"),
                            "cites_sql": bool(cited), "cited_sql_reproduces": reproduces})
                print(f"{'PASS' if ok else 'FAIL'}  {question}: {got!r}" + ("" if ok else f" (trusted: {expected!r})"))
    summary = {"questions": len(out), "passed": sum(r["pass"] for r in out), "traps": sum(r["trap"] for r in out),
               "traps_passed": sum(r["pass"] for r in out if r["trap"]), "tools": tool_names,
               "median_ms": sorted(r["ms"] for r in out)[len(out) // 2],
               "answers_citing_sql": sum(r["cites_sql"] for r in out),
               "cited_sql_reproduced": sum(r["cited_sql_reproduces"] is True for r in out)}
    (ROOT / "evals" / "results.json").write_text(json.dumps({"summary": summary, "results": out}, indent=1, default=str))
    print(json.dumps(summary, indent=1))
    return summary["passed"] == summary["questions"]


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
