"""The object store must answer every question identically on DuckDB and Postgres.

Each case is a function from a store to a result; it runs on both backends and the
results must match exactly. That is what lets the API swap its storage engine
without callers noticing.
"""

import pytest

from atlas.ontology import OntologyQueryError

CASES = {
    # Single objects
    "get county": lambda s: s.get("County", "06025"),
    "get earthquake": lambda s: s.get("Earthquake", "av1"),
    "get missing": lambda s: s.get("County", "99999"),
    # Ordering and paging (including mixed-case names, which depend on collation)
    "default order": lambda s: s.objects("County").fetch(),
    "order by name": lambda s: s.objects("County").fetch(order_by="name"),
    "order by magnitude desc": lambda s: s.objects("Earthquake").fetch(order_by="magnitude", descending=True),
    "nulls last": lambda s: s.objects("Earthquake").fetch(order_by="county_geoid"),
    "paging": lambda s: s.objects("Earthquake").fetch(order_by="occurred_at", limit=2, offset=2),
    # Filters of every operator and property type
    "eq string": lambda s: s.objects("County").where("state", "eq", "CA").fetch(),
    "ne string": lambda s: s.objects("County").where("state", "ne", "CA").fetch(),
    "gte double": lambda s: s.objects("Earthquake").where("magnitude", "gte", 2).fetch(),
    "gte double as text": lambda s: s.objects("Earthquake").where("magnitude", "gte", "1.9").fetch(),
    "gt integer": lambda s: s.objects("County").where("active_alert_count", "gt", 0).fetch(),
    "lt integer": lambda s: s.objects("Earthquake").where("significance", "lt", 60).fetch(),
    "contains is case-insensitive": lambda s: s.objects("Earthquake").where("place", "contains", "CALEXICO").fetch(),
    "is_null": lambda s: s.objects("Earthquake").where("county_geoid", "is_null").fetch(),
    "is_not_null": lambda s: s.objects("County").where("max_alert_severity", "is_not_null").fetch(),
    "timestamp gte": lambda s: s.objects("Earthquake").where("occurred_at", "gte", "2026-10-21T00:00:00Z").fetch(),
    "boolean eq": lambda s: s.objects("Earthquake").where("tsunami_flag", "eq", "true").fetch(),
    "chained filters": lambda s: s.objects("County").where("active_alert_count", "gt", 0).where("recent_quake_count", "gt", 0).fetch(),
    "count": lambda s: s.objects("Earthquake").where("magnitude", "gte", 1.5).count(),
    # Link traversal in every direction
    "many-to-one, forward": lambda s: s.objects("Earthquake").where("magnitude", "gte", 2).search_around("county").fetch(),
    "many-to-one, reverse": lambda s: s.linked("County", "06025", "earthquakes", order_by="occurred_at"),
    "many-to-many, forward": lambda s: s.linked("WeatherAlert", "a2", "counties"),
    "many-to-many, reverse": lambda s: s.linked("County", "06025", "weatherAlerts", order_by="sent_at", descending=True),
    "two hops": lambda s: s.objects("Earthquake").where("magnitude", "gte", 1).search_around("county").search_around("weatherAlerts").fetch(),
    # Aggregations
    "group by string": lambda s: s.objects("WeatherAlert").aggregate([("severity", None)]),
    "ties are deterministic": lambda s: s.objects("County").aggregate([("state", None)]),
    "bucket by day with metric": lambda s: s.objects("Earthquake").aggregate([("occurred_at", "day")], [("max", "magnitude"), ("avg", "depth_km")]),
    "bucket by hour": lambda s: s.objects("Earthquake").where("county_geoid", "eq", "06025").aggregate([("occurred_at", "hour")]),
    "no grouping": lambda s: s.objects("Earthquake").aggregate([], [("sum", "significance")]),
}


@pytest.mark.parametrize("case", CASES)
def test_backends_agree(case, duck_store, pg_store):
    query = CASES[case]
    assert query(pg_store) == query(duck_store)


@pytest.mark.parametrize(
    "bad_query",
    [
        lambda s: s.objects("Earthquake").where("magnitude", "gte", "not a number").fetch(),
        lambda s: s.objects("Earthquake").where("occurred_at", "gte", "yesterday-ish").fetch(),
        lambda s: s.objects("Earthquake").where("nope", "eq", 1).fetch(),
        lambda s: s.objects("Earthquake").search_around("nope").fetch(),
    ],
)
def test_bad_queries_are_caller_errors_on_both(bad_query, duck_store, pg_store):
    for store in (duck_store, pg_store):
        with pytest.raises(OntologyQueryError):
            bad_query(store)
