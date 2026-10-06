-- Census Gazetteer -> clean.county_base (status columns are added in 04_county_status.sql)
CREATE OR REPLACE TABLE clean.county_base AS
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
);
