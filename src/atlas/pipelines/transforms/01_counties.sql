-- Census reference files -> clean.county_base (+ population) and clean.county_shapes
-- (County status columns are added last, in 09_county_status.sql.)
CREATE OR REPLACE TABLE clean.county_base AS
WITH gazetteer AS (
    SELECT
        geoid,
        name,
        state,
        land_area_sqmi::DOUBLE        AS land_area_sqmi,
        latitude::DOUBLE              AS latitude,
        trim(longitude)::DOUBLE       AS longitude
    FROM read_csv(
        '{landing}/census_counties/*.txt',
        delim = '\t',
        header = true,
        all_varchar = true,
        names = ['state', 'geoid', 'ansicode', 'name', 'aland', 'awater',
                 'land_area_sqmi', 'awater_sqmi', 'latitude', 'longitude']
    )
),
population AS (
    -- SUMLEV 050 = county rows (040 rows are state totals).
    SELECT "STATE" || "COUNTY" AS geoid, "POPESTIMATE2024"::BIGINT AS population
    FROM read_csv(
        '{landing}/census_counties/co-est2024-alldata.csv',
        header = true, all_varchar = true, encoding = 'latin-1'
    )
    WHERE "SUMLEV" = '050'
)
SELECT g.*, p.population
FROM gazetteer g
LEFT JOIN population p USING (geoid);

-- County polygons, for point-in-county matching of earthquakes, facilities and fires.
CREATE OR REPLACE TABLE clean.county_shapes AS
SELECT "GEOID" AS geoid, geom
FROM ST_Read('/vsizip/{landing}/census_counties/cb_2024_us_county_500k.zip/cb_2024_us_county_500k.shp')
WHERE "GEOID" IN (SELECT geoid FROM clean.county_base);
