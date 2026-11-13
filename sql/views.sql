-- The business definitions, written once in SQL so every tool and test uses the same logic.

-- Points races only (race_type_id = 1), with track type attached.
CREATE OR REPLACE VIEW points_results AS
SELECT x.*, r.race_name, r.race_date, r.track_name, t.track_type, r.playoff_round,
       x.finish_pos = 1 AS win,
       x.finish_pos <= 5 AS top5,
       x.finish_pos <= 10 AS top10,
       x.start_pos = 1 AS pole,
       (x.status <> 'Running' AND x.status <> '') AS dnf
FROM results x
JOIN races r USING (race_id)
JOIN tracks t USING (track_name)
WHERE r.race_type_id = 1;

-- One row per driver-season: the numbers a season-stat question should return.
CREATE OR REPLACE VIEW driver_season AS
WITH s AS (
    SELECT season, driver_id, any_value(driver) AS driver,
           count(*) AS starts,
           sum(win::INT) AS wins, sum(top5::INT) AS top5s, sum(top10::INT) AS top10s,
           sum(pole::INT) AS poles, sum(dnf::INT) AS dnfs,
           sum(laps_led) AS laps_led, round(avg(finish_pos), 2) AS avg_finish,
           round(avg(start_pos), 2) AS avg_start, sum(points) AS points
    FROM points_results
    GROUP BY season, driver_id
)
SELECT * FROM s;

-- Race-level competitiveness for fans: lead changes, leaders, cautions and the finish.
CREATE OR REPLACE VIEW race_excitement AS
SELECT r.race_id, r.season, r.race_name, r.race_date, r.track_name, t.track_type,
       r.lead_changes, r.leaders, r.cautions, r.caution_laps, r.margin_of_victory,
       r.lead_changes * 100.0 / nullif(r.actual_laps, 0) AS lead_changes_per_100_laps
FROM races r JOIN tracks t USING (track_name)
WHERE r.race_type_id = 1;
