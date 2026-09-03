#!/usr/bin/env python3
"""Verify DB connectivity for the configured backend (SQLite or Impala).

Backend is chosen by DB_BACKEND in backend/.env ("sqlite" default, or "impala").
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test database connection")
    parser.add_argument("--query", default="SELECT 1 AS ok", help="SQL to run after connecting")
    args = parser.parse_args()

    from config import get_settings
    from database import create_db_engine, test_db_connection
    from sqlalchemy import text

    s = get_settings()
    if s.uses_impala:
        print("Backend: impala")
        print(f"  host:           {s.impala_host}")
        print(f"  port:           {s.impala_port}")
        print(f"  database:       {s.impala_database}")
        print(f"  auth:           {s.impala_auth_mechanism}")
        print(f"  http_path:      {s.impala_http_path}")
        print(f"  use_ssl:        {s.impala_use_ssl}")
        print(f"  http_transport: {s.impala_use_http_transport}")
        if s.impala_user:
            print(f"  user:           {s.impala_user}")
    else:
        print("Backend: sqlite")
        print(f"  url:            {s.database_url}")

    try:
        test_db_connection()
        print("\n✓ Connected (SELECT 1 succeeded)")
    except Exception as exc:
        print(f"\n✗ Connection failed: {exc}", file=sys.stderr)
        return 1

    q = args.query.strip()
    if q.upper() not in {"SELECT 1", "SELECT 1 AS OK"}:
        try:
            with create_db_engine().connect() as conn:
                rows = conn.execute(text(q)).fetchall()
            print(f"\nQuery: {q}")
            for row in rows[:20]:
                print(" ", row)
            if len(rows) > 20:
                print(f"  ... ({len(rows) - 20} more rows)")
        except Exception as exc:
            print(f"\n✗ Query failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
