-- county_base + current hazards -> clean.counties
-- Derived properties: each County carries a summary of what is happening in it right now,
-- so a map can colour every county from one object load instead of N link traversals.
CREATE OR REPLACE TABLE clean.counties AS
WITH alerts AS (
    SELECT
        ac.geoid,
        count(*) AS active_alert_count,
        max(CASE w.severity
            WHEN 'Extreme' THEN 4 WHEN 'Severe' THEN 3
            WHEN 'Moderate' THEN 2 WHEN 'Minor' THEN 1 ELSE 0 END) AS max_alert_severity_rank
    FROM clean.alert_counties ac
    JOIN clean.weather_alerts w USING (alert_id)
    GROUP BY ac.geoid
),
quakes AS (
    SELECT
        county_geoid AS geoid,
        count(*) AS recent_quake_count,
        max(magnitude) AS max_quake_magnitude
    FROM clean.earthquakes
    WHERE county_geoid IS NOT NULL
      AND occurred_at >= now() - INTERVAL 7 DAY
    GROUP BY county_geoid
)
SELECT
    c.*,
    coalesce(a.active_alert_count, 0)       AS active_alert_count,
    coalesce(a.max_alert_severity_rank, 0)  AS max_alert_severity_rank,
    CASE a.max_alert_severity_rank
        WHEN 4 THEN 'Extreme' WHEN 3 THEN 'Severe'
        WHEN 2 THEN 'Moderate' WHEN 1 THEN 'Minor' END AS max_alert_severity,
    coalesce(q.recent_quake_count, 0)       AS recent_quake_count,
    q.max_quake_magnitude
FROM clean.county_base c
LEFT JOIN alerts a USING (geoid)
LEFT JOIN quakes q USING (geoid);
