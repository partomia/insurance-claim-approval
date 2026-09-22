"""Reusable CLI for the Iceberg time-travel/audit story (Item 3 of the
OLTP+lakehouse enhancements, see cde/README.md § "Iceberg time travel").

The gold tables (insurance_lakehouse.{policy_master,policy_clauses,
policy_risk_signals,garage_risk_signals}) now write via MERGE INTO instead
of drop+recreate (cde/jobs/curate/curate_gold.py,
curate_risk_signals_gold.py), so every pipeline run commits a real Iceberg
snapshot -- this is a `test-claim`-style wrapper around the raw Impala SQL
(DESCRIBE HISTORY / FOR SYSTEM_TIME|VERSION AS OF) so you don't have to
hand-type it in Hue every time.

Two subcommands:

  history  -- list every snapshot committed to a gold table.
  as-of    -- read a table as it looked at a past snapshot/timestamp, and
              print it side-by-side with the current row(s) for an
              at-a-glance diff.

Usage (via cml/cli.sh, run from repo root):
    bash cml/cli.sh lakehouse history --table policy_risk_signals
    bash cml/cli.sh lakehouse as-of --table policy_risk_signals \\
        --policy-number LH-POL-2059 --snapshot 4967580225782225719
    bash cml/cli.sh lakehouse as-of --table policy_risk_signals \\
        --policy-number LH-POL-2059 --at "2026-09-21 12:00:00"

Or directly:
    cd backend
    uv run python scripts/lakehouse_time_travel.py history --table policy_risk_signals
    uv run python scripts/lakehouse_time_travel.py as-of --table garage_risk_signals \\
        --garage-name "Rapid Repairs Garage, Mumbai" --at "2026-09-20 00:00:00"

Confirmed against CDP 7.3.2's documented Impala Iceberg support (not
guessed) -- see cde/README.md § Iceberg time travel for the doc links.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402
from database import _impala_connect  # noqa: E402

settings = get_settings()

GOLD_TABLES = ["policy_master", "policy_clauses", "policy_risk_signals", "garage_risk_signals"]


def db_name() -> str:
    return settings.lakehouse_database


def _print_table(headers: list[str], rows: list[tuple]) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))


def cmd_history(args: argparse.Namespace) -> None:
    conn = _impala_connect(database=db_name())
    try:
        cur = conn.cursor()
        sql = f"DESCRIBE HISTORY {db_name()}.{args.table}"
        if args.since:
            sql += f" FROM '{args.since}'"
        cur.execute(sql)
        rows = cur.fetchall()
        headers = [d[0] for d in cur.description]
        rows = rows[-args.limit :]
        print(f"=== Snapshot history: {db_name()}.{args.table} ===")
        _print_table(headers, rows)
        print(f"\n{len(rows)} snapshot(s) shown (most recent last).")
        if len(rows) > 1:
            print(
                "Use one of the snapshot_id values above with:\n"
                f"  bash cml/cli.sh lakehouse as-of --table {args.table} --snapshot <snapshot_id> ..."
            )
    finally:
        conn.close()


def _where_clause(args: argparse.Namespace) -> str:
    if args.where:
        return f" WHERE {args.where}"
    if args.policy_number:
        return f" WHERE policy_number = '{args.policy_number}'"
    if args.garage_name:
        return f" WHERE garage_name = '{args.garage_name}'"
    return ""


def cmd_as_of(args: argparse.Namespace) -> None:
    if not args.snapshot and not args.at:
        print("[error] as-of needs either --snapshot <id> or --at '<timestamp>'", file=sys.stderr)
        sys.exit(1)

    where = _where_clause(args)
    conn = _impala_connect(database=db_name())
    try:
        cur = conn.cursor()

        if args.snapshot:
            past_sql = f"SELECT * FROM {db_name()}.{args.table} FOR SYSTEM_VERSION AS OF {args.snapshot}{where}"
            label = f"snapshot {args.snapshot}"
        else:
            past_sql = f"SELECT * FROM {db_name()}.{args.table} FOR SYSTEM_TIME AS OF '{args.at}'{where}"
            label = f"'{args.at}'"

        cur.execute(past_sql)
        past_rows = cur.fetchall()
        headers = [d[0] for d in cur.description]

        cur.execute(f"SELECT * FROM {db_name()}.{args.table}{where}")
        current_rows = cur.fetchall()

        print(f"=== {db_name()}.{args.table} AS OF {label} ===")
        _print_table(headers, past_rows)
        print(f"\n=== {db_name()}.{args.table} CURRENT ===")
        _print_table(headers, current_rows)

        if len(past_rows) == 1 and len(current_rows) == 1 and past_rows[0] != current_rows[0]:
            print("\n=== Diff (changed columns only) ===")
            for i, h in enumerate(headers):
                if past_rows[0][i] != current_rows[0][i]:
                    print(f"  {h}: {past_rows[0][i]}  ->  {current_rows[0][i]}")
        elif past_rows == current_rows:
            print("\n(no difference between the two points in time for this filter)")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_history = sub.add_parser("history", help="List every snapshot committed to a gold table")
    p_history.add_argument("--table", required=True, choices=GOLD_TABLES)
    p_history.add_argument("--since", help="Only show snapshots from this timestamp onward (DESCRIBE HISTORY ... FROM)")
    p_history.add_argument("--limit", type=int, default=20)
    p_history.set_defaults(func=cmd_history)

    p_asof = sub.add_parser(
        "as-of", help="Read a gold table as of a past snapshot/timestamp, diffed against the current row"
    )
    p_asof.add_argument("--table", required=True, choices=GOLD_TABLES)
    p_asof.add_argument("--snapshot", help="Snapshot ID from `history`'s output")
    p_asof.add_argument("--at", help="UTC timestamp, e.g. '2026-09-21 12:00:00'")
    p_asof.add_argument("--policy-number", help="Convenience filter: policy_number = '...' (policy_* tables)")
    p_asof.add_argument("--garage-name", help="Convenience filter: garage_name = '...' (garage_risk_signals)")
    p_asof.add_argument("--where", help="Raw SQL WHERE fragment, overrides --policy-number/--garage-name")
    p_asof.set_defaults(func=cmd_as_of)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
