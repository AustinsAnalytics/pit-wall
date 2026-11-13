"""Pit Wall MCP server: NASCAR Cup Series data (2022-2026) for AI assistants, over stdio.

Every answer carries the exact SQL that produced it ("sql") and the definitions it used ("basis"), so a person can
check any AI answer by running one query.

    python -m pitwall.server

Tool descriptions carry the business definitions, because that is where AI answers go wrong: counting the Clash as a
win, calling a DVP finish 'running', picking the wrong Charlotte. Every tool is checked against trusted SQL in evals/.
"""
from mcp.server.mcpserver import MCPServer

from pitwall import tools

mcp = MCPServer("pit-wall", instructions="NASCAR Cup Series data, 2022-2026. Call describe_data first; season stats count points races only.")


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except tools.ToolError as e:
        return {"error": str(e)}


@mcp.tool()
def describe_data() -> dict:
    """Start here. Lists the tables and columns, the seasons covered (2022-2026 Cup Series), the six track types and
    the business definitions every answer must follow: wins, top 10s, poles, DNFs and averages count POINTS RACES
    ONLY (the Clash, Daytona Duels and All-Star races are excluded)."""
    return _call(tools.describe_data)


@mcp.tool()
def driver_season_stats(driver: str, season: int) -> dict:
    """One driver's points-race season: starts, wins, top5s, top10s, poles, dnfs, laps_led, avg_finish, avg_start,
    points. Accepts a full or last name; returns an error listing the options if the name is ambiguous (e.g. 'Dillon')."""
    return _call(tools.driver_season_stats, driver, season)


@mcp.tool()
def season_leaders(season: int, stat: str = "wins", top_n: int = 10) -> dict:
    """Leaderboard for one season (points races only). stat: wins, top5s, top10s, poles, dnfs, laps_led, points,
    starts, avg_finish or avg_start (the two averages rank lowest first and require 10+ starts). Ties are broken
    alphabetically, so check the stat value before calling someone the sole leader."""
    return _call(tools.season_leaders, season, stat, top_n)


@mcp.tool()
def track_history(track: str, since_season: int = 2022) -> dict:
    """Points-race winners at a track since a season (inclusive) and the average lead changes, cautions and margin of
    victory there. 'Charlotte' means the oval; ask for 'Charlotte Motor Speedway Road Course' for the Roval."""
    return _call(tools.track_history, track, since_season)


@mcp.tool()
def race_result(season: int, race: str, top_n: int = 40) -> dict:
    """Finishing order of one points race, by track name, race name or YYYY-MM-DD date. Tracks that host two races a
    season (e.g. Daytona, Talladega, Martinsville) return an error listing both; then ask by race name or date."""
    return _call(tools.race_result, season, race, top_n)


@mcp.tool()
def excitement_by_track_type(season: int | None = None) -> dict:
    """How competitive races are by track type: average lead changes, cautions, margin of victory (seconds) and the
    share of photo finishes (margin under 0.1 s), for points races, optionally for one season."""
    return _call(tools.excitement_by_track_type, season)


@mcp.tool()
def top10_probability(driver: str, track: str, start_pos: int) -> dict:
    """Model estimate of the chance a driver finishes in the top 10 from a starting spot at a track, using his form
    entering the most recent race in the data. Calibrated on 2026 races held out from training; see the site for
    accuracy. A forecast, not a certainty."""
    from pitwall import model
    return _call(model.top10_probability, driver, track, start_pos)


@mcp.tool()
def run_sql(sql: str, max_rows: int = 200) -> dict:
    """Read-only SQL over DuckDB for anything the other tools don't cover. One SELECT/WITH statement; writes are
    refused. Use the points_results view (points races only, with win/top5/top10/pole/dnf flags and track_type) for
    stats, so answers match the official definitions."""
    return _call(tools.run_sql, sql, max_rows)


if __name__ == "__main__":
    mcp.run()
