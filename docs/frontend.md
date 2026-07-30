# Frontend

Vite + React + TypeScript + Tailwind. Root: `frontend/src`.

## Pages (`frontend/src/pages/`)

### Customer portal

| File | Route | Purpose |
|------|-------|---------|
| `Auth.tsx` | `/auth` | Signup / login |
| `Dashboard.tsx` | `/` | Home aggregates + shortcut to file a claim |
| `Profile.tsx` | `/profile` | Customer profile, KYC status, saved contacts |
| `KYC.tsx` | `/kyc` | Doc upload, mobile OTP, face verification |
| `ConnectPolicy.tsx` | `/policies/connect` | Import policy from external insurer (OTP demo) |
| `ClaimForm.tsx` / `ClaimWizard.tsx` | `/claims/new` | Guided claim submission |
| `ClaimAnalysis.tsx` | `/claims/:id/analysis` | AI decision breakdown |
| `TrackClaim.tsx` | `/claims/:id/track` | Status timeline + copilot chat pane |
| `AuditReport.tsx` | `/claims/:id/audit` | Regulator-ready audit view |
| `History.tsx` | `/history` | Past claims |

### Agent (Expert Copilot) portal — `pages/agent/`
Assigned queue, per-claim review, expert copilot chat.

### Insurer portal — `pages/insurer/`
Back-office approve/reject queue.

## Shared components

`frontend/src/components/` groups by concern:
- Chat surface (used by customer + expert copilots).
- Form primitives (inputs, upload dropzones).
- Claim insights (score gauges, payout breakdown, timeline).
- Layout (sidebar, header, portal switch).

## Data plumbing

- API client + auth headers: `frontend/src/lib/api.ts` (single fetch wrapper).
- Session state: local storage token; refresh on 401.

## Assistant memory in the UI

- The customer chat pane uses `GET /api/assistant/chat` (with optional
  `?thread_id=…&claim_id=…`) and `POST /api/assistant/chat`.
- `GET /api/assistant/threads` powers the multi-thread switcher.
- Per-claim chat on the Track Claim page uses `/api/claims/{id}/chat`.
- Expert chat uses `/api/agent/assistant/chat` — same three-tier memory
  layer server-side.

All three surfaces share one backend memory model — see
[`assistant-memory.md`](./assistant-memory.md).
