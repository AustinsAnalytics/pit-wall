"""Collect evaluation results, trap analysis, model metrics and fan metrics into site/data.json.

    python pipeline/export_site.py
"""
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from pitwall import model, server, tools  # noqa: E402


def main():
    ev = json.loads((ROOT / "evals" / "results.json").read_text())
    traps = json.loads((ROOT / "evals" / "traps.json").read_text())
    m = json.loads((ROOT / "data" / "model.json").read_text())
    build = json.loads((ROOT / "data" / "build_checks.json").read_text())
    tool_docs = []
    for name in ev["summary"]["tools"]:
        fn = getattr(server, name)
        tool_docs.append({"name": name, "signature": str(inspect.signature(fn)).replace("'", ""),
                          "description": " ".join(inspect.getdoc(fn).split())})
    data = {
        "evals": ev, "traps": traps,
        "model": {k: m[k] for k in ("train", "test", "metrics", "calibration", "coefficients", "form_as_of")},
        "examples": {
            "top10": [model.top10_probability("Kyle Larson", "Martinsville", 5),
                      model.top10_probability("Tyler Reddick", "Talladega", 30)],
            "dillon": server.driver_season_stats("Dillon", 2024),
            "byron": tools.driver_season_stats("William Byron", 2025),
        },
        "excitement": tools.excitement_by_track_type(),
        "definitions": tools.describe_data()["definitions"],
        "track_types": tools.describe_data()["track_types"],
        "tools": tool_docs, "build": build,
    }
    out = ROOT / "site" / "data.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(data, default=str, separators=(",", ":")))
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
