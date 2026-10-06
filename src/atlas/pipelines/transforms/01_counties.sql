-- Census Gazetteer -> clean.counties
CREATE OR REPLACE TABLE clean.counties AS
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
