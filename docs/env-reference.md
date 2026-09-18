# Environment reference

All settings live in `backend/config.py` (`Settings`). Values are read from
`backend/.env`; `backend/.env.example` is the annotated template.

## Core

| Var | Default | Notes |
|---|---|---|
| `DB_BACKEND` | `sqlite` | `sqlite` (default, local/CML) or `impala` (swaps the app's own OLTP DB to Impala — not recommended, see `cml/README.md`) |
| `IMPALA_HOST` | `go01-aws-rtdm-gateway...` | CDP Impala gateway host |
| `IMPALA_PORT` | `443` | |
| `IMPALA_DATABASE` | `default` | Impala schema/database (only used when `DB_BACKEND=impala`) |
| `IMPALA_USE_SSL` | `true` | |
| `IMPALA_USE_HTTP_TRANSPORT` | `true` | HiveServer2 over HTTP (CDP proxy) vs. binary |
| `IMPALA_AUTH_MECHANISM` | `GSSAPI` | Kerberos; use `LDAP` + `IMPALA_USER`/`IMPALA_PASSWORD` locally |
| `IMPALA_HTTP_PATH` | `go01-aws-rtdm/cdp-proxy-api/impala` | CDP proxy path |
| `IMPALA_KERBEROS_SERVICE_NAME` | `impala` | Only used when `IMPALA_AUTH_MECHANISM=GSSAPI` |
| `IMPALA_USER` / `IMPALA_PASSWORD` | empty | LDAP credentials when Kerberos unavailable |
| `LAKEHOUSE_DATABASE` | `insurance_lakehouse` | Iceberg schema for the datalakehouse story (`cml/cli.sh lakehouse seed\|verify\|ingest`, `cde/` pipeline) — reuses the `IMPALA_*` connection settings above but is **independent of `DB_BACKEND`**; the app can stay on SQLite while this is seeded/queried. See `cml/README.md` § Data lakehouse |
| `REDIS_URL` | `redis://redis:6379/0` | Celery broker + result backend |
| `JWT_SECRET` | `cloudera-insurance-secret-key-for-demo` | **Rotate in prod** |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_EXPIRE_MINUTES` | `10080` | Access token (7d) |
| `JWT_REFRESH_DAYS` | `30` | Refresh token TTL |

## LLM

| Var | Default | Notes |
|---|---|---|
| `GROQ_API_KEY` | empty | Required for real replies; without it the copilots fall back to templates |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Swap to any Groq-hosted model |
| `OPENAI_API_KEY` | empty | Used for embeddings; without it Chroma uses random vectors (dev only) |
| `OPENAI_MODEL` | `gpt-4o` | Reserved; not currently used at runtime |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model for policy RAG |

## Pipeline / risk thresholds

| Var | Default | Notes |
|---|---|---|
| `CLAIM_PROCESSING_MODE` | `auto` | `auto` / `sync` / `celery` |
| `FRAUD_ESCALATE_THRESHOLD` | `0.75` | ≥ this → escalate |
| `FRAUD_REVIEW_THRESHOLD` | `0.40` | ≥ this → human review |
| `EVIDENCE_REVIEW_THRESHOLD` | `0.55` | Evidence confidence to auto-approve |
| `EARLY_CLAIM_DAYS` | `14` | Claims filed within N days flagged |
| `HUMAN_REVIEW_AMOUNT_THRESHOLD` | `500000` | Claims over this → review |
| `CONFIDENCE_REVIEW_THRESHOLD` | `0.60` | Below this → review |
| `MAX_UPLOAD_SIZE_MB` | `25` | |

## Storage

| Var | Default | Notes |
|---|---|---|
| `CHROMA_DB_PATH` | `backend/chroma_db` | Persisted vector store |
| `CHROMA_COLLECTION_NAME` | `insurance_policies` | |
| `UPLOAD_DIR` | `backend/storage` | Set to `/app/storage` in Docker |

## Deployment

| Var | Default | Notes |
|---|---|---|
| `ROOT_PATH` | empty | Set to `/proxy/<port>` behind Cloudera CML |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated; add your prod frontend |
| `AGENT_INVITE_CODE` | `CLOUDERA2026` | Invite required to register as expert |

## Assistant memory (STM + LTM) — v2

Tune to trade prompt cost vs. context depth. Defaults are sane for local dev.

| Var | Default | Effect |
|---|---|---|
| `ASSISTANT_RECENT_TURN_LIMIT` | `8` | Verbatim recent turns in every prompt |
| `ASSISTANT_COMPACTION_MESSAGE_THRESHOLD` | `16` | Message count needed to trigger compaction |
| `ASSISTANT_COMPACTION_CHAR_THRESHOLD` | `6000` | Total chars needed to trigger compaction (both thresholds must exceed) |
| `ASSISTANT_SUMMARY_CHAR_CAP` | `1500` | Hard cap on persisted summary size |
| `ASSISTANT_MAX_LONG_TERM_FACTS` | `20` | Cap on per-persona LTM entries |
| `ASSISTANT_HISTORY_LIMIT` | `30` | Rows returned by `GET /chat` history endpoints |
| `ASSISTANT_SUMMARY_MAX_TOKENS` | `512` | LLM budget for compaction call |
| `ASSISTANT_LTM_EXTRACT_MAX_TOKENS` | `256` | Reserved; combined call currently uses `SUMMARY_MAX_TOKENS` |
| `ASSISTANT_BACKFILL_ON_STARTUP` | `true` | Run legacy chat → v2 backfill on every boot. Flip to `false` in prod after first successful migration |

### Recommended profiles

**Low-cost / long-thread** (many turns, cheap):
```
ASSISTANT_RECENT_TURN_LIMIT=4
ASSISTANT_COMPACTION_MESSAGE_THRESHOLD=10
ASSISTANT_COMPACTION_CHAR_THRESHOLD=3000
ASSISTANT_SUMMARY_MAX_TOKENS=384
```

**High-fidelity / short-thread** (few turns, best replies):
```
ASSISTANT_RECENT_TURN_LIMIT=16
ASSISTANT_COMPACTION_MESSAGE_THRESHOLD=40
ASSISTANT_COMPACTION_CHAR_THRESHOLD=12000
ASSISTANT_SUMMARY_MAX_TOKENS=800
```

**Prod steady-state:**
```
ASSISTANT_BACKFILL_ON_STARTUP=false   # after first successful boot
```

## Verifying an override

```bash
ASSISTANT_RECENT_TURN_LIMIT=3 \
  ./backend/.venv/bin/python -c \
  "from config import get_settings; \
   print(get_settings().assistant_recent_turn_limit)"
# 3
```
