-- USGS landing (append-only history) -> clean.earthquakes
CREATE OR REPLACE TABLE clean.earthquakes AS
WITH raw AS (
    SELECT * FROM read_json(
        '{landing}/usgs_earthquakes/*.ndjson',
        format = 'newline_delimited',
        columns = {
            id: 'VARCHAR', mag: 'DOUBLE', place: 'VARCHAR', time: 'BIGINT', updated: 'BIGINT',
            url: 'VARCHAR', alert: 'VARCHAR', status: 'VARCHAR', tsunami: 'INTEGER', sig: 'INTEGER',
            type: 'VARCHAR', longitude: 'DOUBLE', latitude: 'DOUBLE', depth: 'DOUBLE'
        }
    )
    WHERE type = 'earthquake'
),

-- An event is re-landed every time USGS revises it; keep only the latest revision.
latest AS (
    SELECT * FROM raw
    QUALIFY row_number() OVER (PARTITION BY id ORDER BY updated DESC) = 1
),

-- Link each event to the nearest county centroid (haversine distance), within 100 km.
distances AS (
    SELECT
        e.id,
        c.geoid,
        2 * 6371 * asin(sqrt(
            pow(sin(radians(c.latitude - e.latitude) / 2), 2)
            + cos(radians(e.latitude)) * cos(radians(c.latitude))
              * pow(sin(radians(c.longitude - e.longitude) / 2), 2)
        )) AS km
    FROM latest e
    CROSS JOIN clean.counties c
),
nearest AS (
    SELECT id, arg_min(geoid, km) AS geoid, min(km) AS km
    FROM distances
    GROUP BY id
    HAVING min(km) <= 100
)

SELECT
    e.id                                AS event_id,
    e.mag                               AS magnitude,
    e.place,
    make_timestamptz(e.time * 1000)     AS occurred_at,
    make_timestamptz(e.updated * 1000)  AS updated_at,
    e.latitude,
    e.longitude,
    e.depth                             AS depth_km,
    e.sig                               AS significance,
    e.tsunami = 1                       AS tsunami_flag,
    e.alert                             AS pager_alert,
    e.status                            AS review_status,
    n.geoid                             AS county_geoid,
    round(n.km, 1)                      AS distance_to_county_km,
    e.url
FROM latest e
LEFT JOIN nearest n USING (id);
