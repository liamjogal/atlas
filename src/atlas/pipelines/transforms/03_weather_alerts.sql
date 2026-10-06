-- NWS landing (snapshots) -> clean.weather_alerts + clean.alert_counties
-- Only the most recent snapshot is "current": anything not in it has expired.
CREATE OR REPLACE TEMP TABLE latest_alerts AS
WITH raw AS (
    SELECT * FROM read_json(
        '{landing}/nws_alerts/*.ndjson',
        format = 'newline_delimited',
        filename = true,
        columns = {
            id: 'VARCHAR', event: 'VARCHAR', headline: 'VARCHAR', severity: 'VARCHAR',
            urgency: 'VARCHAR', certainty: 'VARCHAR', areaDesc: 'VARCHAR', senderName: 'VARCHAR',
            sent: 'TIMESTAMPTZ', effective: 'TIMESTAMPTZ', expires: 'TIMESTAMPTZ',
            description: 'VARCHAR', instruction: 'VARCHAR', same_codes: 'VARCHAR[]'
        }
    )
)
SELECT * FROM raw
WHERE filename = (SELECT max(filename) FROM raw)
QUALIFY row_number() OVER (PARTITION BY id) = 1;

CREATE OR REPLACE TABLE clean.weather_alerts AS
SELECT
    id              AS alert_id,
    event,
    headline,
    severity,
    urgency,
    certainty,
    areaDesc        AS area_description,
    senderName      AS sender,
    sent            AS sent_at,
    effective       AS effective_at,
    expires         AS expires_at,
    description,
    instruction
FROM latest_alerts;

-- Join table backing the many-to-many WeatherAlert <-> County link.
-- SAME code = '0' + 5-digit county FIPS; non-county codes (marine zones) drop out in the join.
CREATE OR REPLACE TABLE clean.alert_counties AS
SELECT DISTINCT a.id AS alert_id, c.geoid
FROM (SELECT id, unnest(same_codes) AS same_code FROM latest_alerts) a
JOIN clean.counties c ON c.geoid = substr(a.same_code, 2);
