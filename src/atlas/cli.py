import argparse
import json
import logging

from atlas.config import ONTOLOGY_PATH
from atlas.db import connect


def cmd_sync(args) -> None:
    from atlas.sync import run_sync

    print(json.dumps(run_sync(), indent=2))


def cmd_index(args) -> None:
    from atlas.sync import run_sync

    print(json.dumps(run_sync(pull=False), indent=2))


def cmd_facilities(args) -> None:
    from atlas.connectors import geofabrik

    print(json.dumps(geofabrik.refresh_due(force=args.force), indent=2))
    print("Run `uv run atlas index` (or let the worker cycle) to load them into the object store.")


def cmd_worker(args) -> None:
    from atlas.sync import run_worker

    try:
        run_worker(args.every)
    except KeyboardInterrupt:
        print("worker stopped")


def cmd_validate(args) -> None:
    from atlas.ontology import load_ontology

    ontology = load_ontology(ONTOLOGY_PATH)
    print(f"Ontology parsed: {len(ontology.object_types)} object types, {len(ontology.link_types)} link types")
    with connect(read_only=True) as con:
        problems = ontology.validate_against(con)
    if problems:
        print("Problems found:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)
    print("Ontology matches the data.")


def cmd_serve(args) -> None:
    import uvicorn

    from atlas.api import create_app

    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        # Behind a load balancer, trust its X-Forwarded-* headers for the client address and scheme.
        proxy_headers=args.behind_proxy,
        forwarded_allow_ips="*" if args.behind_proxy else None,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # httpx logs full request URLs at INFO, and some (FIRMS) carry an API key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="atlas", description="An ontology platform for live disaster response")
    sub = parser.add_subparsers(required=True)

    sync = sub.add_parser("sync", help="Run one cycle: pull sources, rebuild datasets, index objects")
    sync.set_defaults(func=cmd_sync)

    index = sub.add_parser("index", help="Rebuild datasets and re-index objects from already-landed data")
    index.set_defaults(func=cmd_index)

    facilities = sub.add_parser("facilities", help="Build OSM facilities from Geofabrik extracts now (first run downloads ~12 GB)")
    facilities.add_argument("--force", action="store_true", help="Refresh every region, even if fresh")
    facilities.set_defaults(func=cmd_facilities)

    worker = sub.add_parser("worker", help="Run sync cycles on a schedule (the only process that writes)")
    worker.add_argument("--every", type=int, default=300, metavar="SECONDS",
                        help="Seconds between cycles (default 300)")
    worker.set_defaults(func=cmd_worker)

    validate = sub.add_parser("validate", help="Check ontology.yaml against the clean datasets")
    validate.set_defaults(func=cmd_validate)

    serve = sub.add_parser("serve", help="Run the Ontology API (read-only; run `atlas worker` alongside)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--behind-proxy", action="store_true", help="Trust X-Forwarded-* headers (behind a load balancer)")
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)
