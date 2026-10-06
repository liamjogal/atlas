import argparse
import json
import logging

from atlas.config import DB_PATH, ONTOLOGY_PATH
from atlas.db import connect


def cmd_sync(args) -> None:
    from atlas.sync import run_sync

    with connect() as con:
        print(json.dumps(run_sync(con), indent=2))


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

    if not DB_PATH.exists():
        raise SystemExit("No data yet. Run `uv run atlas sync` first.")
    uvicorn.run(create_app(sync_every=args.sync_every), host=args.host, port=args.port)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="atlas", description="A mini Palantir-style ontology platform")
    sub = parser.add_subparsers(required=True)

    sync = sub.add_parser("sync", help="Pull all sources and rebuild clean datasets once")
    sync.set_defaults(func=cmd_sync)

    validate = sub.add_parser("validate", help="Check ontology.yaml against the clean datasets")
    validate.set_defaults(func=cmd_validate)

    serve = sub.add_parser("serve", help="Run the Ontology API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--sync-every", type=int, default=300, metavar="SECONDS",
                       help="Re-sync live sources on this interval (0 to disable, default 300)")
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)
