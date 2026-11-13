# Pit Wall

**A validated AI analyst for NASCAR Cup Series data.** An MCP server that lets AI assistants (Claude and other MCP
clients) answer NASCAR questions from a SQL database, with the business definitions built into every tool, and a test
suite that checks every answer against trusted SQL.

**Site: [austinsanalytics.github.io/pit-wall](https://austinsanalytics.github.io/pit-wall/)**

## What's here

| | |
|---|---|
| `pipeline/fetch.py` | Every Cup Series race 2022-2026 from NASCAR's public results feeds (204 races, 7,340 driver results) |
| `pipeline/build.py`, `sql/views.sql` | DuckDB database. Wins, top 10s, poles, DNFs and averages are defined once, in SQL, for points races only |
| `pitwall/tools.py` | The analysis functions: driver seasons, leaderboards, track history, race results, fan metrics, read-only SQL |
| `pitwall/server.py` | The MCP server: eight tools whose descriptions carry the definitions and ask instead of guessing |
| `pitwall/model.py` | Top-10 finish probability: logistic regression on pre-race facts; trained 2022-2025, tested on 2026 |
| `evals/run_evals.py` | Starts the server, calls every tool through the MCP protocol, compares each answer with trusted SQL |

## Results

- **Every answer shows its work:** each tool returns the definitions it applied and the exact SQL behind the
  answer. The suite reruns all 21 cited queries; each reproduces its answer exactly.
- **25 of 25** questions answered correctly through the MCP protocol, including **6 of 6** traps: exhibition races
  counted as wins (adds 24 phantom wins and creates a false co-leader in 2022), ambiguous driver names (Dillon, Busch,
  Burton...), tracks that host two races a season, and unsafe SQL.
- **Top-10 forecast on 2026 (never seen in training):** AUC 0.781 vs 0.746 for the starting grid alone; log loss
  0.484 vs 0.516; the model's 10 likeliest drivers per race finish top 10 53% of the time vs 50% for the first 10 on the grid.
- **Fan lens:** superspeedways average 46.8 lead changes a race and 54.5% of them finish within a tenth of a second.

## Run it

```sh
pip install -r requirements.txt
python pipeline/fetch.py && python pipeline/build.py
python -m pitwall.model
python evals/run_evals.py          # must print 25/25
python -m pitwall.server           # MCP server over stdio
```

Claude Desktop configuration:

```json
{"mcpServers": {"pit-wall": {"command": "python", "args": ["-m", "pitwall.server"], "cwd": "/path/to/pit-wall"}}}
```

## Limits

The suite validates tools through the protocol; it does not grade a model's free-form wording (the harness can grade
any assistant's tool calls). Track types are a documented judgment call. The forecast's edge over the grid is modest
and it knows nothing about pit strategy, wrecks or weather.

---

By Austin Gentile. Built with Claude Code (Anthropic) as an AI pair programmer; every number comes from this code and
is checked by its test suite. Independent project, not affiliated with or endorsed by NASCAR. Data: NASCAR's public
results feeds.
