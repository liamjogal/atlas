-- OSM facility features (osmium export from Geofabrik extracts, one file per region) -> clean.facilities
CREATE OR REPLACE TABLE clean.facilities AS
WITH raw AS (
    SELECT geometry, properties AS tags
    FROM read_json(
        '{landing}/osm_facilities/*.geojsonseq',
        format = 'newline_delimited',
        columns = {geometry: 'JSON', properties: 'JSON'}
    )
),

features AS (
    SELECT
        (tags->>'@type') || '/' || (tags->>'@id')                AS osm_id,
        tags,
        ST_Centroid(ST_GeomFromGeoJSON(geometry))                AS point,
        -- osmium exports a closed way twice (as a line and as an area); prefer the area.
        CASE WHEN (geometry->>'type') LIKE '%Polygon' THEN 0 ELSE 1 END AS shape_rank
    FROM raw
),

unique_features AS (
    SELECT * FROM features
    -- also dedupes a place present in two overlapping regional extracts
    QUALIFY row_number() OVER (PARTITION BY osm_id ORDER BY shape_rank) = 1
),

-- One row per kind the place has: a school that is also a shelter is two facilities.
with_kind AS (
    SELECT f.*, k.kind
    FROM unique_features f
    JOIN (VALUES ('hospital'), ('school'), ('fire_station'), ('shelter')) AS k(kind)
      -- (JSON lookups are parenthesised: in DuckDB, = binds tighter than ->>.)
      ON (k.kind = 'shelter' AND (f.tags->>'social_facility') = 'shelter')
      OR (k.kind <> 'shelter' AND (f.tags->>'amenity') = k.kind)
),

-- The county that contains it. Extracts reach across borders; those points drop out here.
located AS (
    SELECT w.*, s.geoid AS county_geoid
    FROM with_kind w
    JOIN clean.county_shapes s ON ST_Contains(s.geom, w.point)
    QUALIFY row_number() OVER (PARTITION BY w.kind, w.osm_id ORDER BY s.geoid) = 1
)

SELECT
    kind || '/' || osm_id                                         AS facility_id,
    osm_id,
    kind,
    -- Many OSM places have no name; give every facility a readable title.
    coalesce(tags->>'name', 'Unnamed ' || replace(kind, '_', ' ')) AS name,
    ST_Y(point)                                                   AS latitude,
    ST_X(point)                                                   AS longitude,
    county_geoid,
    nullif(concat_ws(', ',
        nullif(concat_ws(' ', tags->>'addr:housenumber', tags->>'addr:street'), ''),
        tags->>'addr:city', tags->>'addr:state', tags->>'addr:postcode'), '') AS address,
    tags->>'operator'                                             AS operator,
    -- capacity/beds are free text in OSM ("about 50"); keep only clean numbers.
    TRY_CAST(coalesce(tags->>'capacity', tags->>'beds') AS BIGINT) AS capacity,
    coalesce((tags->>'emergency') = 'yes', false)                    AS emergency
FROM located;
