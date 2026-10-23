-- NASA FIRMS landing (append-only, last day per sync) -> clean.fire_detections (last 7 days)
CREATE OR REPLACE TABLE clean.fire_detections AS
WITH raw AS (
    SELECT * FROM read_json(
        '{landing}/firms_fires/*.ndjson',
        format = 'newline_delimited',
        columns = {
            latitude: 'DOUBLE', longitude: 'DOUBLE', acq_date: 'VARCHAR', acq_time: 'VARCHAR',
            satellite: 'VARCHAR', confidence: 'VARCHAR', frp: 'DOUBLE', daynight: 'VARCHAR'
        }
    )
),

parsed AS (
    SELECT
        -- FIRMS has no detection id; position + time + satellite identifies one.
        substr(md5(concat_ws('|', latitude, longitude, acq_date, acq_time, satellite)), 1, 16) AS detection_id,
        latitude,
        longitude,
        (acq_date || ' ' || substr(acq_time, 1, 2) || ':' || substr(acq_time, 3, 2) || ':00+00')::TIMESTAMPTZ
            AS detected_at,
        satellite,
        confidence,
        frp,
        daynight
    FROM raw
),

recent AS (
    SELECT * FROM parsed
    WHERE detected_at >= now() - INTERVAL 7 DAY
    -- Each sync re-lands the last day, so most detections arrive several times.
    QUALIFY row_number() OVER (PARTITION BY detection_id) = 1
)

SELECT
    r.detection_id,
    'Fire detection ' || strftime(r.detected_at, '%b %d %H:%M UTC')  AS label,
    r.latitude,
    r.longitude,
    r.detected_at,
    r.satellite,
    r.confidence,
    r.frp,
    r.daynight                                                        AS day_night,
    s.geoid                                                           AS county_geoid
FROM recent r
JOIN clean.county_shapes s ON ST_Contains(s.geom, ST_Point(r.longitude, r.latitude))
QUALIFY row_number() OVER (PARTITION BY r.detection_id ORDER BY s.geoid) = 1;
