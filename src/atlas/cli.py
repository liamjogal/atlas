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

    uvicorn.run(create_app(), host=args.host, port=args.port)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="atlas", description="An ontology platform for live disaster response")
    sub = parser.add_subparsers(required=True)

    sync = sub.add_parser("sync", help="Run one cycle: pull sources, rebuild datasets, index objects")
    sync.set_defaults(func=cmd_sync)

    index = sub.add_parser("index", help="Rebuild datasets and re-index objects from already-landed data")
    index.set_defaults(func=cmd_index)

    worker = sub.add_parser("worker", help="Run sync cycles on a schedule (the only process that writes)")
    worker.add_argument("--every", type=int, default=300, metavar="SECONDS",
                        help="Seconds between cycles (default 300)")
    worker.set_defaults(func=cmd_worker)

    validate = sub.add_parser("validate", help="Check ontology.yaml against the clean datasets")
    validate.set_defaults(func=cmd_validate)

    serve = sub.add_parser("serve", help="Run the Ontology API (read-only; run `atlas worker` alongside)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)
