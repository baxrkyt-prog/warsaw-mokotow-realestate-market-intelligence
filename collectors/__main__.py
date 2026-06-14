"""
CLI dla collectors.

Użycie:
  python -m collectors list
  python -m collectors run <source> [opcje source-specific]
  python -m collectors run csv_import --file fixtures/sample.csv --mapping fixtures/sample.mapping.json
  python -m collectors run xlsx_import --file data.xlsx --mapping mapping.json --sheet Sheet1
"""

import argparse
import sys
import time

from .registry import all_collectors, get_collector


def cmd_list(_args) -> int:
    cols = all_collectors()
    if not cols:
        print("(brak zarejestrowanych collectorów)")
        return 0
    print(f"{'SOURCE':<24} {'KIND':<14} {'VER':<5} DESCRIPTION")
    print("-" * 78)
    for src in sorted(cols):
        c = cols[src]
        print(f"{src:<24} {c.kind:<14} {c.schema_version:<5} {c.description}")
    return 0


def cmd_run(args) -> int:
    cls = get_collector(args.source)
    # Sparsuj source-specific args
    sub = argparse.ArgumentParser(prog=f"collectors run {args.source}")
    cls.add_cli_args(sub)
    sub_args, _ = sub.parse_known_args(args.rest)

    instance = cls()
    t0 = time.time()
    result = instance.run(**vars(sub_args))
    result.duration_ms = int((time.time() - t0) * 1000)

    instance.log_to_ingestion(result)

    print(f"\n=== {args.source} done ===")
    print(f"  status:           {result.status}")
    print(f"  records_in:       {result.records_in}")
    print(f"  records_new:      {result.records_new}")
    print(f"  records_updated:  {result.records_updated}")
    print(f"  records_rejected: {result.records_rejected}")
    if result.rejection_reasons:
        for reason, n in sorted(result.rejection_reasons.items(), key=lambda x: -x[1]):
            print(f"      • {reason}: {n}")
    if result.error_msg:
        print(f"  error: {result.error_msg}")
    if result.extras:
        print(f"  extras:")
        for k, v in result.extras.items():
            print(f"      • {k}: {v}")
    print(f"  duration_ms:      {result.duration_ms}")
    return 0 if result.status == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collectors")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    pr = sub.add_parser("run")
    pr.add_argument("source", help="ID źródła (zobacz: collectors list)")
    pr.add_argument("rest", nargs=argparse.REMAINDER)
    pr.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
