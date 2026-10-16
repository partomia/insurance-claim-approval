# Project log — Motor Claim Copilot on Cloudera (`mcc`)

Every live action, run id, count and plan change, newest last. No secret values.
Earlier history of this repo (go01 env 1, AWC env 2) is in `MEMORY_DUMP.md`.

## 2026-10-16 12:10 - Discovery (read-only)

- **Target environment** `federal-cdp-env`, same as the sibling demos (OGX, CXR):
  CAI workspace `federal-cml-ws` (`https://federal-cml.federal.dp5i-5vkq.cloudera.site`),
  CDE `federal-cde` / `federal-cde-vc` (local `~/.cde/config.yaml` already points at it,
  CLI 1.23.0), CDW `federal-impala-1`, Kafka Data Hub `federal-kafka`, bucket
  `federal-buk-574bcea0`. Connection details taken from `O-G-Asset-Integrity-Lakehouse/.env`
  (names only read here).
- **CAI** projects listed: 11, none with `mcc`. **CDE** jobs listed: 54, prefixes
  casa/churn/coll/cxr/gdl/mule/ogx/spend; no `mcc`.
- **Data Visualization** primary keys in use by siblings: 7000–13599 → `mcc` takes 14000+.
- **GitHub** `partomia/insurance-claim-approval` is **private** → CDE files resource from
  `git archive`, blank CAI project + file push (CXR/OGX pattern).
- **Plan change: target environment.** Earlier work ran on go01 (env 1, `rsingh-insurance-*`,
  `insurance_lakehouse*`) and AWC (env 2, OLTP only). The use case is now built on
  federal under the `mcc` prefix; the go01/AWC deployments and their files on `main`
  are left untouched.
- No LLM key (Groq / AI Inference) exists in any local `.env`; the app on federal starts
  with its deterministic fallback until one is supplied.
- Public dataset chosen: `fraud_oracle.csv` (carclaims), CC0, 15,420 rows.
- `PLAN.md` written; branch `feature/cloudera-mcc`.
