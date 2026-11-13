"""Top-10 finish probability: features known before the green flag, trained on 2022-2025, tested on 2026.

    python -m pitwall.model     -> data/model.json (coefficients, test metrics, calibration) and data/model_report.json

Features (all from races strictly before the one being predicted):
  start position (log), driver's average finish and top-10 rate over his previous 10 points races, his average finish
  at the same track type over his previous 8 such races, his team's average finish over its previous 10 races,
  field size, and the track type.
"""
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "pitwall.duckdb"
OUT = ROOT / "data" / "model.json"
FIELD_AVG = 18.5
TYPES = ["superspeedway", "intermediate", "short_track", "one_mile_flat", "large_flat", "road_course"]
NUM = ["log_start", "form_avg_finish", "form_top10_rate", "type_avg_finish", "team_avg_finish", "field_size"]


def features(con=None):
    con = con or duckdb.connect(str(DB), read_only=True)
    d = con.execute("""
        SELECT p.race_id, p.season, p.race_date, p.track_name, p.track_type, p.driver_id, p.driver, p.team,
               p.start_pos, p.finish_pos, p.top10::INT AS top10,
               count(*) OVER (PARTITION BY p.race_id) AS field_size
        FROM points_results p ORDER BY p.race_date, p.race_id""").df()
    d = d.sort_values(["race_date", "race_id", "finish_pos"]).reset_index(drop=True)
    g = d.groupby("driver_id", sort=False)
    d["form_avg_finish"] = g.finish_pos.transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
    d["form_top10_rate"] = g.top10.transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
    d["type_avg_finish"] = d.groupby(["driver_id", "track_type"], sort=False).finish_pos.transform(
        lambda s: s.shift().rolling(8, min_periods=1).mean())
    team_race = d.groupby(["team", "race_id", "race_date"], as_index=False).finish_pos.mean().sort_values("race_date")
    team_race["team_avg_finish"] = team_race.groupby("team").finish_pos.transform(
        lambda s: s.shift().rolling(10, min_periods=1).mean())
    d = d.merge(team_race[["team", "race_id", "team_avg_finish"]], on=["team", "race_id"], how="left")
    for c in ("form_avg_finish", "type_avg_finish", "team_avg_finish"):
        d[c] = d[c].fillna(FIELD_AVG)
    d["form_top10_rate"] = d["form_top10_rate"].fillna(0.27)
    d["log_start"] = np.log(d.start_pos.clip(lower=1))
    return d


def design(d, mu=None, sd=None):
    X = d[NUM].astype(float)
    mu = X.mean() if mu is None else mu
    sd = X.std() if sd is None else sd
    Z = (X - mu) / sd
    for t in TYPES[1:]:
        Z[f"type_{t}"] = (d.track_type == t).astype(float)
    return Z, mu, sd


def picks_hit_rate(df, score):
    """In each race, take the 10 highest-scored drivers; share of them who actually finished top 10."""
    hits = df.assign(s=score).groupby("race_id", group_keys=False).apply(
        lambda g: g.nlargest(10, "s").top10.mean(), include_groups=False)
    return float(hits.mean())


def main():
    d = features()
    train, test = d[d.season <= 2025], d[d.season == 2026]
    Xtr, mu, sd = design(train)
    Xte, _, _ = design(test, mu, sd)
    full = LogisticRegression(C=1.0, max_iter=2000).fit(Xtr, train.top10)
    base = LogisticRegression(max_iter=2000).fit(Xtr[["log_start"]], train.top10)
    p_full, p_base = full.predict_proba(Xte)[:, 1], base.predict_proba(Xte[["log_start"]])[:, 1]
    rate = float(train.top10.mean())
    metrics = {}
    for name, p in (("model", p_full), ("starting_spot_only", p_base), ("constant_rate", np.full(len(test), rate))):
        metrics[name] = {"log_loss": float(log_loss(test.top10, p)), "brier": float(brier_score_loss(test.top10, p)),
                         "auc": float(roc_auc_score(test.top10, p)) if name != "constant_rate" else 0.5}
    metrics["model"]["top10_picks_hit_rate"] = picks_hit_rate(test, p_full)
    metrics["starting_spot_only"]["top10_picks_hit_rate"] = picks_hit_rate(test, -test.start_pos.values)
    bins = np.clip((p_full * 10).astype(int), 0, 9)
    calib = [{"bin": int(b), "pred": float(p_full[bins == b].mean()), "actual": float(test.top10.values[bins == b].mean()),
              "n": int((bins == b).sum())} for b in range(10) if (bins == b).any()]
    coefs = dict(zip(Xtr.columns, map(float, full.coef_[0])))
    # latest form for every driver/team/track type, for the live tool
    latest = d.sort_values("race_date").groupby("driver_id").tail(10)
    form = d.sort_values("race_date").groupby("driver_id").agg(driver=("driver", "last"), team=("team", "last"))
    form["form_avg_finish"] = latest.groupby("driver_id").finish_pos.mean()
    form["form_top10_rate"] = latest.groupby("driver_id").top10.mean()
    by_type = d.sort_values("race_date").groupby(["driver_id", "track_type"]).tail(8).groupby(
        ["driver_id", "track_type"]).finish_pos.mean()
    team_form = d.sort_values("race_date").groupby("team").tail(30).groupby("team").finish_pos.mean()
    report = {
        "train": {"seasons": "2022-2025", "rows": int(len(train)), "races": int(train.race_id.nunique())},
        "test": {"season": 2026, "rows": int(len(test)), "races": int(test.race_id.nunique())},
        "metrics": metrics, "calibration": calib, "coefficients": coefs,
        "intercept": float(full.intercept_[0]), "mu": mu.to_dict(), "sd": sd.to_dict(),
        "form_as_of": str(d.race_date.max()),
        "drivers": {int(i): {"driver": r.driver, "team": r.team, "form_avg_finish": float(r.form_avg_finish),
                             "form_top10_rate": float(r.form_top10_rate),
                             "by_type": {t: float(by_type.get((i, t), FIELD_AVG)) for t in TYPES}}
                    for i, r in form.iterrows()},
        "team_avg_finish": {k: float(v) for k, v in team_form.items()},
    }
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("train", "test", "metrics", "coefficients")}, indent=1))


def top10_probability(driver, track, start_pos):
    from pitwall import tools
    m = json.loads(OUT.read_text())
    d = tools.find_driver(driver)
    t = tools.find_track(track)
    ttype = tools._rows("SELECT track_type FROM tracks WHERE track_name = ?", (t,))[0]["track_type"]
    info = m["drivers"].get(str(d["driver_id"]))
    if info is None:
        raise tools.ToolError(f"No recent form for {d['driver']}.")
    if not 1 <= int(start_pos) <= 40:
        raise tools.ToolError("start_pos must be between 1 and 40.")
    x = {"log_start": np.log(int(start_pos)), "form_avg_finish": info["form_avg_finish"],
         "form_top10_rate": info["form_top10_rate"], "type_avg_finish": info["by_type"][ttype],
         "team_avg_finish": m["team_avg_finish"].get(info["team"], FIELD_AVG), "field_size": 38}
    z = sum(m["coefficients"][k] * (x[k] - m["mu"][k]) / m["sd"][k] for k in NUM)
    z += m["coefficients"].get(f"type_{ttype}", 0.0) + m["intercept"]
    p = 1 / (1 + np.exp(-z))
    return {"driver": d["driver"], "track": t, "track_type": ttype, "start_pos": int(start_pos),
            "top10_probability": round(float(p), 3), "form_as_of": m["form_as_of"],
            "inputs": {k: round(float(v), 2) for k, v in x.items()}}


if __name__ == "__main__":
    main()
