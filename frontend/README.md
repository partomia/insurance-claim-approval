# Claim app frontend

React + TypeScript + Vite SPA with three portals over the FastAPI backend. Components and
routes in detail: [`docs/frontend.md`](../docs/frontend.md); setup: the
[root README](../README.md).

## Portals and routes

| Portal | Routes |
|--------|--------|
| Customer | `/auth`, `/dashboard`, `/kyc`, `/policies/connect`, `/profile`, `/claim`, `/claim/:id`, `/track/:id` (live pipeline), `/analysis/:id`, `/audit/:id`, `/history` |
| Expert / agent | `/agent/auth`, `/agent/dashboard`, `/agent/claims`, `/agent/claims/:id`, `/agent/claims/:id/audit`, `/agent/customers/:id`, `/agent/profile` |
| Insurer | `/insurer/auth`, `/insurer/dashboard`, `/insurer/book-of-business`, `/insurer/claims`, `/insurer/claims/:id`, `/insurer/claims/:id/audit` |

The shadow approval-model score (mcc) appears only in the agent and insurer views, never to
customers.

## Commands

```bash
npm ci
npm run dev        # http://localhost:5173 (./start.sh runs this with the backend)
npm run build      # tsc -b && vite build → dist/
npm run lint       # oxlint
```

## Configuration

`VITE_API_URL` (template [`.env.example`](.env.example)): the backend base URL. Leave it empty
for same-origin deploys (FastAPI serving `dist/` with `SERVE_FRONTEND=true`, or the Vite dev
proxy). Set it only when the SPA is hosted elsewhere, e.g. Vercel calling a backend in a CAI
Session.

## On Cloudera AI

- **federal (mcc):** the workbench cannot reach the Node installer, so build on a laptop and
  upload: `(cd frontend && VITE_API_URL="" npm run build) && python ci/push_files.py --dist`.
- **go01 / AWC:** `bash cml/cli.sh setup` builds `dist/` inside the CAI Session.
