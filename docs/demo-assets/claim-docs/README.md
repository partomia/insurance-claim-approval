# Demo claim-evidence documents

Synthetic (generated, not real) documents for manually exercising the claim
submission wizard's **Step 3: Evidence Upload**, e.g. to test the Phase 4
**Claim Insights risk card** by submitting a claim against a lakehouse
(`LH-POL-*`) policy — see `cml/README.md` § Phase 4 for the full walkthrough
(reset a lakehouse customer's password with
`backend/scripts/set_demo_password.py`, log in, submit a claim).

Every file is watermarked "SYNTHETIC TEST DOCUMENT ... Not a real document" —
these are plain generated images, not real photos/IDs.

| File | Wizard field |
|---|---|
| `damage_photo_front.jpg`, `damage_photo_side.jpg` | Damage photos (required) |
| `driver_license.jpg` | Driver's licence (required if KYC not verified for the test customer) |
| `repair_estimate.jpg` | Repair estimate / garage invoice (optional) |
| `vehicle_registration.jpg` | Vehicle registration / RC (optional) |
| `police_report.jpg` | Police / FIR report (required only if third-party/injuries flagged in Step 1) |

Regenerate (e.g. to target a different policy/customer) with:

```bash
cd backend
uv run python scripts/generate_demo_claim_docs.py \
  --policy-number LH-POL-2050 --customer-name "Ananya Iyer" --vehicle "Volkswagen Taigun"
```
