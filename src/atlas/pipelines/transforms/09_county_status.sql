-- county_base + current hazards and assets -> clean.counties (runs last: it summarises the others)
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
),
facilities AS (
    SELECT
        county_geoid AS geoid,
        count(*) FILTER (WHERE kind = 'hospital')      AS hospital_count,
        count(*) FILTER (WHERE kind = 'shelter')       AS shelter_count,
        count(*) FILTER (WHERE kind = 'fire_station')  AS fire_station_count,
        count(*) FILTER (WHERE kind = 'school')        AS school_count
    FROM clean.facilities
    GROUP BY county_geoid
),
fires AS (
    SELECT county_geoid AS geoid, count(*) AS active_fire_count
    FROM clean.fire_detections
    WHERE detected_at >= now() - INTERVAL 24 HOUR
    GROUP BY county_geoid
)
SELECT
    c.*,
    coalesce(a.active_alert_count, 0)       AS active_alert_count,
    coalesce(a.max_alert_severity_rank, 0)  AS max_alert_severity_rank,
    CASE a.max_alert_severity_rank
        WHEN 4 THEN 'Extreme' WHEN 3 THEN 'Severe'
        WHEN 2 THEN 'Moderate' WHEN 1 THEN 'Minor'
        WHEN 0 THEN 'Unknown' END AS max_alert_severity,  -- NWS rates some alerts (e.g. air quality) Unknown
    coalesce(q.recent_quake_count, 0)       AS recent_quake_count,
    q.max_quake_magnitude,
    coalesce(f.hospital_count, 0)           AS hospital_count,
    coalesce(f.shelter_count, 0)            AS shelter_count,
    coalesce(f.fire_station_count, 0)       AS fire_station_count,
    coalesce(f.school_count, 0)             AS school_count,
    coalesce(fi.active_fire_count, 0)       AS active_fire_count
FROM clean.county_base c
LEFT JOIN alerts a USING (geoid)
LEFT JOIN quakes q USING (geoid)
LEFT JOIN facilities f USING (geoid)
LEFT JOIN fires fi USING (geoid);
