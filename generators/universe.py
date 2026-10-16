"""
The seeded motor-insurance world every source is generated from (standard library only, so the
laptop, CI and the CDE land job share it).

  customers   800 people; customer{i}@example.com holds LH-POL-{2000+i} (the app's lakehouse
              policies), ~8% hold a second policy LH-POL-28xx. Latent traits: care (drives credit,
              violations, tenure), financial stress, cross-insurer claiming, address churn,
              fraud-proneness. No protected attributes; driver_age exists for analytics only.
  policies    one vehicle each (VIN, registration), IDV = coverage_limit, renewed yearly; the
              current term is anchored to the first business date so the book stays in force.
  garages     40 network garages, 3 of them high-risk (2 on the insurer's WATCHLIST).
  claims      ~4,000 over the 24 months before the first business date plus ~40 FNOL a day.
              Fraud is a latent draw; it shifts the observable signals (garage, inflated amount,
              no telematics crash, VIN mismatch, no police report, late intimation) and the
              outcome follows from those signals plus noise, so a model can learn it (the
              Step 5 blocker: outcomes used to be drawn independently of every feature).
  telematics  crash events for ~70% of vehicles: genuine collisions usually have one, staged
              ones rarely do; plus false-alarm impacts.

World(seed).day(d) returns every source's records for one business date, so any date can be
(re)landed on its own and every run gives the same files.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "lakehouse.json").read_text())
DATES = [date.fromisoformat(d) for d in
         CFG["business_dates"] + [CFG["live_date"]] + CFG.get("scheduled_dates", [])]
U = CFG["universe"]

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Rahul", "Amit", "Suresh", "Vikram", "Sanjay", "Rajesh",
         "Kiran", "Ravi", "Karthik", "Arun", "Naveen", "Imran", "Joseph", "Gurpreet", "Venkatesh", "Priya",
         "Ananya", "Sneha", "Pooja", "Neha", "Kavya", "Divya", "Lakshmi", "Meena", "Fatima", "Mary", "Simran",
         "Deepa", "Swati", "Nisha", "Rekha"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Shah", "Mehta", "Reddy", "Rao", "Iyer", "Nair",
        "Menon", "Das", "Banerjee", "Ghosh", "Khan", "Shaikh", "Dsouza", "Fernandes", "Joshi", "Kulkarni",
        "Patil", "Yadav", "Mishra", "Agarwal", "Jain", "Bhat", "Gill", "Kapoor"]
CITIES = [("Mumbai", "MH", "02"), ("Pune", "MH", "12"), ("Delhi", "DL", "03"), ("Bengaluru", "KA", "01"),
          ("Chennai", "TN", "09"), ("Hyderabad", "TS", "07"), ("Ahmedabad", "GJ", "01"), ("Kolkata", "WB", "02"),
          ("Jaipur", "RJ", "14"), ("Lucknow", "UP", "32"), ("Kochi", "KL", "07"), ("Indore", "MP", "09")]
VEHICLES = [("Maruti Suzuki", "Baleno", 750_000), ("Hyundai", "Creta", 1_400_000), ("Tata", "Nexon", 1_050_000),
            ("Honda", "City", 1_250_000), ("Mahindra", "XUV700", 2_000_000), ("Kia", "Seltos", 1_500_000),
            ("Toyota", "Innova", 2_200_000), ("Maruti Suzuki", "Swift", 650_000), ("Volkswagen", "Taigun", 1_450_000)]
GARAGE_NAMES = [
    "Prime Auto Body Shop", "Speedy Motors", "City Garage", "Highway Auto Care", "Metro Car Clinic", "Elite Motors",
    "Sunrise Auto Works", "Trust Garage", "Precision Auto", "Quick Fix Motors", "Reliable Car Care", "Star Auto Body",
    "National Garage", "Comfort Motors", "Vision Auto Works", "Premier Car Clinic", "Apex Motors", "Zenith Auto",
    "Horizon Garage", "United Auto Care", "Regal Motors", "Diamond Auto Body", "Silver Line Garage", "Classic Car Care",
    "Pioneer Motors", "Sunshine Auto", "Grand Auto Works", "Crown Garage", "Excel Motors", "Fortune Auto Care",
    "Downtown Auto", "Riverside Garage", "Lakeview Motors", "Northside Auto Care", "Southgate Garage",
    "Eastend Motors", "Westpark Auto",
    "Rapid Repairs Garage", "Everfix Auto Body", "Golden Wheels Motors"]   # the last three are high-risk
HIGH_RISK = {"GRG-038", "GRG-039", "GRG-040"}
WATCHLIST = {"GRG-038", "GRG-039"}
# (mean, sd) requested amount in INR per claim type (as the earlier CDE generator)
CLAIM_TYPES = {"Collision": (45_000, 18_000), "Theft": (280_000, 110_000), "Fire": (190_000, 90_000),
               "Glass": (4_500, 1_500), "ThirdParty": (60_000, 28_000), "NaturalDisaster": (130_000, 60_000)}
CLAIM_TYPE_WEIGHTS = {"Collision": 46, "Theft": 6, "Fire": 3, "Glass": 18, "ThirdParty": 17, "NaturalDisaster": 10}
CRASH_TYPES = {"Collision", "ThirdParty"}
CLAUSES = [
    ("Policy Schedule", "Section 1.0",
     "This Motor Comprehensive Policy provides own-damage and third-party liability coverage for the insured "
     "private vehicle for a period of 12 months from the effective date. Insured Declared Value (IDV) is the "
     "maximum settlement amount for total loss."),
    ("Coverage Details", "Section 4.2",
     "Own-damage coverage includes collision, theft, fire, vandalism, natural disasters, and glass breakage. "
     "Third-party liability covers bodily injury and property damage to third parties as required by law."),
    ("Exclusions", "Section 7.1",
     "Exclusions: driving under influence of alcohol or drugs, driving without a valid licence, racing or speed "
     "testing, commercial use without endorsement, consequential loss, mechanical/electrical breakdown, wear and "
     "tear, and damage caused by war or nuclear risks."),
    ("Claim Settlement", "Section 3.5",
     "Deductible applies per own-damage claim. Depreciation applied per the schedule unless the "
     "zero-depreciation add-on is active. Claims must be intimated within 48 hours of the incident."),
]


def R(seed, label: str) -> random.Random:
    return random.Random(f"{seed}:{label}")


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def epoch_ms(dt: datetime) -> int:
    return int((dt - datetime(1970, 1, 1)).total_seconds() * 1000)


def typo(rng: random.Random, s: str) -> str:
    if len(s) < 4:
        return s
    i = rng.randint(1, len(s) - 3)
    return s[:i] + s[i + 1] + s[i] + s[i + 2:] if rng.random() < 0.5 else s[:i] + s[i + 1:]


def fmt_mobile(rng: random.Random, m: str) -> str:
    style = rng.random()
    return m if style < 0.4 else f"+91-{m[:5]} {m[5:]}" if style < 0.7 else f"0{m}" if style < 0.85 else f"+91 {m}"


@dataclass
class Customer:
    idx: int
    customer_ref: str
    first: str
    last: str
    dob: date
    mobile: str
    email: str
    city: str
    customer_since: date
    care: float
    stressed: bool
    cross_claimant: bool
    address_churn: bool
    fraud_prone: bool
    bureau_ref: str
    policies: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


@dataclass
class Policy:
    policy_number: str
    customer: Customer
    provider: str
    premium: float
    status: str
    idv: float
    deductible: float
    co_pay_pct: float
    effective: date
    expiry: date
    depreciation_rate: float
    vin: str
    reg_no: str
    make: str
    model: str
    year: int
    ncb_pct: float
    zero_dep: bool
    rsa: bool
    has_telematics: bool
    book: bool                     # in the app's active book (policy_master)
    customer_ref: str = ""         # the policy-admin customer number (a legacy one on second policies)
    holder_name: str = ""          # as keyed on this policy


@dataclass
class Claim:
    claim_id: str
    policy: Policy
    claim_type: str
    incident: datetime
    fnol: datetime
    city: str
    amount: float
    stated_vin: str
    garage_id: str
    police_report: bool
    third_party: bool
    channel: str
    fraud: bool
    crash_event: bool
    status: str = "FILED"
    amount_approved: float | None = None
    decided: datetime | None = None
    decided_by: str | None = None
    reason_code: str | None = None
    review_at: datetime | None = None


class World:
    def __init__(self, seed: int = CFG["seed"]):
        self.seed = seed
        self.anchor = DATES[0]
        self.customers: list[Customer] = []
        self.policies: dict[str, Policy] = {}
        self.garages: list[dict] = []
        self.claims: list[Claim] = []
        self.crash_events: list[dict] = []
        self._build_customers()
        self._build_policies()
        self._build_garages()
        self._build_claims()
        self._build_telematics()
        self.day1_policies = [self.policy_row(p, datetime.combine(p.effective, datetime.min.time()))
                              for p in self.policies.values()]
        self._build_cdc()

    # ------------------------------------------------------------ people and policies

    def _build_customers(self) -> None:
        rng = R(self.seed, "customers")
        mobiles = set()
        for i in range(U["customers"]):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            while True:
                m = rng.choice("6789") + f"{rng.randint(0, 999_999_999):09d}"
                if m not in mobiles:
                    mobiles.add(m)
                    break
            care = rng.betavariate(5, 2)
            self.customers.append(Customer(
                idx=i, customer_ref=f"PA-C{100000 + i:06d}", first=first, last=last,
                dob=date(1956, 1, 1) + timedelta(days=rng.randint(0, 17_000)), mobile=m,
                email=f"customer{i}@example.com", city=rng.choice(CITIES)[0],
                customer_since=self.anchor - timedelta(days=int(rng.uniform(0.3, 1 + care * 11) * 365)),
                care=care, stressed=rng.random() < 0.07, cross_claimant=rng.random() < 0.04,
                address_churn=rng.random() < 0.03, fraud_prone=rng.random() < 0.035,
                bureau_ref=f"BU{30000000 + rng.randint(0, 69_999_999):08d}"))

    def _policy(self, rng, number: str, c: Customer, book: bool) -> Policy:
        make, model, price = rng.choice(VEHICLES)
        year = rng.randint(2016, 2025)
        idv = round(price * max(0.4, 1 - 0.08 * (self.anchor.year - year)) * rng.uniform(0.9, 1.05), -3)
        effective = self.anchor - timedelta(days=rng.randint(30, 300))
        city, state, rto = next(x for x in CITIES if x[0] == c.city)
        vin = "MA" + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(15))
        p = Policy(
            policy_number=number, customer=c, provider=rng.choice(CFG["insurer"]["provider_names"]),
            premium=round(idv * rng.uniform(0.018, 0.032), 2),
            status=rng.choices(["ACTIVE", "EXPIRED", "LAPSED", "CANCELLED"], weights=[85, 6, 6, 3])[0],
            idv=idv, deductible=rng.choice([500.0, 750.0, 1000.0, 2000.0]), co_pay_pct=round(rng.uniform(0, 15), 1),
            effective=effective, expiry=effective + timedelta(days=365), depreciation_rate=round(rng.uniform(5, 25), 1),
            vin=vin, reg_no=f"{state}-{rto}-{rng.choice('ABCDEFGHJK')}{rng.choice('ABCDEFGHJK')}-{rng.randint(1000, 9999)}",
            make=make, model=model, year=year, ncb_pct=rng.choice([0, 20, 25, 35, 45, 50]),
            zero_dep=rng.random() < 0.45, rsa=rng.random() < 0.5,
            has_telematics=rng.random() < U["telematics_fraction"], book=book)
        p.customer_ref, p.holder_name = c.customer_ref, c.name
        c.policies.append(p)
        self.policies[number] = p
        return p

    def _build_policies(self) -> None:
        rng = R(self.seed, "policies")
        for c in self.customers:
            p = self._policy(rng, f"LH-POL-{2000 + c.idx}", c, book=c.idx < U["active_book"])
            if p.book and p.status != "ACTIVE" and c.idx % 4:     # most of the app's book is in force
                p.status = "ACTIVE"
        extra = rng.sample(self.customers, int(len(self.customers) * U["second_policy_fraction"]))
        for k, c in enumerate(sorted(extra, key=lambda x: x.idx)):
            p = self._policy(rng, f"LH-POL-{2800 + k}", c, book=False)
            # sold through the legacy branch system: its own customer number, the name as keyed there
            p.customer_ref = f"PA-C{900000 + k:06d}"
            if rng.random() < 0.5:
                p.holder_name = f"{c.first[0]}. {c.last}" if rng.random() < 0.5 else f"{typo(rng, c.first)} {c.last}"

    def _build_garages(self) -> None:
        rng = R(self.seed, "garages")
        for i, name in enumerate(GARAGE_NAMES[: U["garages"]]):
            gid = f"GRG-{i + 1:03d}"
            city = CITIES[i % len(CITIES)][0]
            self.garages.append({
                "garage_id": gid, "garage_name": f"{name}, {city}", "city": city,
                "network_status": "WATCHLIST" if gid in WATCHLIST else rng.choice(["PREFERRED", "STANDARD", "STANDARD"]),
                "onboarded_on": (date(2015, 1, 1) + timedelta(days=rng.randint(0, 3000))).isoformat(),
                "labour_rate": round(rng.uniform(600, 1400), 2)})
        self.normal_garages = [g["garage_id"] for g in self.garages if g["garage_id"] not in HIGH_RISK]
        self.risky_garages = sorted(HIGH_RISK)

    # ------------------------------------------------------------ claims

    def _claim(self, rng, cid: str, p: Policy, fnol: datetime) -> Claim:
        c = p.customer
        ctype = rng.choices(list(CLAIM_TYPE_WEIGHTS), weights=list(CLAIM_TYPE_WEIGHTS.values()))[0]
        fraud = rng.random() < (0.025 + 0.30 * c.fraud_prone + 0.05 * c.stressed + 0.03 * (ctype == "Theft"))
        delay = rng.expovariate(1 / (4.0 if fraud else 0.8))
        incident = fnol - timedelta(days=min(delay, 25), seconds=rng.randint(0, 6 * 3600))
        mean, sd = CLAIM_TYPES[ctype]
        amount = max(800.0, rng.normalvariate(mean, sd))
        if rng.random() < (0.40 if fraud else 0.03):
            amount *= rng.uniform(2.2, 3.8)
        amount = round(min(amount, p.idv * 1.1), 2)
        garage = (rng.choice(self.risky_garages) if rng.random() < (0.55 if fraud else 0.05)
                  else rng.choice(self.normal_garages))
        vin = p.vin
        if rng.random() < (0.12 if fraud else 0.003):
            vin = "MA" + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(15))
        police = rng.random() < ({"Theft": 0.95, "Fire": 0.7, "ThirdParty": 0.6}.get(ctype, 0.35) * (0.55 if fraud else 1))
        crash = p.has_telematics and ctype in CRASH_TYPES and rng.random() < (0.15 if fraud else 0.9)
        return Claim(cid, p, ctype, incident, fnol, c.city if rng.random() < 0.85 else rng.choice(CITIES)[0],
                     amount, vin, garage, police, ctype == "ThirdParty" or rng.random() < 0.1,
                     rng.choices(["APP", "CALL_CENTRE", "AGENT"], weights=[45, 40, 15])[0], fraud, crash)

    def _adjudicate(self, rng, cl: Claim) -> None:
        """Outcome from the observable signals + the latent fraud + noise (learnable, not deterministic)."""
        p = cl.policy
        c = p.customer
        mean = CLAIM_TYPES[cl.claim_type][0]
        late = (cl.fnol - cl.incident).days >= 2
        outlier = cl.amount > 2 * mean
        noisy = rng.gauss(0, 0.5)
        if cl.fraud and rng.random() < 0.8:          # SIU confirms most staged claims
            cl.status, cl.decided_by, cl.reason_code = "REJECTED", "FRAUD_SIU", "FRAUD_CONFIRMED"
            cl.decided = cl.fnol + timedelta(days=rng.uniform(4, 20))
            cl.review_at = cl.fnol + timedelta(hours=rng.uniform(2, 30))
            return
        z = (2.6 + 4.0 * (c.care - 0.7) - 1.6 * late - 1.5 * outlier - 1.4 * (cl.garage_id in HIGH_RISK)
             - 2.0 * (cl.stated_vin != p.vin) - 1.5 * (cl.claim_type == "Theft" and not cl.police_report)
             - 1.0 * (cl.amount > 0.8 * p.idv) - 1.4 * c.stressed - 1.0 * c.cross_claimant
             + 0.6 * cl.crash_event - 0.6 * (cl.claim_type in CRASH_TYPES and p.has_telematics and not cl.crash_event)
             + noisy)
        approve = rng.random() < sigmoid(z)
        auto = approve and cl.amount < 50_000 and not outlier and not late and rng.random() < 0.75
        cl.status = "APPROVED" if approve else "REJECTED"
        cl.decided_by = "AUTO" if auto else "ADJUSTER"
        cl.reason_code = None if approve else rng.choice(["LATE_INTIMATION", "NOT_COVERED", "DOCS_INSUFFICIENT",
                                                         "EXCLUSION", "AMOUNT_NOT_SUPPORTED"])
        if approve:
            dep = 0 if p.zero_dep else p.depreciation_rate / 100 * rng.uniform(0.3, 1)
            cl.amount_approved = round(max(0.0, cl.amount * (1 - dep) * (1 - p.co_pay_pct / 100) - p.deductible), 2)
        if auto:
            cl.decided = cl.fnol + timedelta(minutes=rng.uniform(3, 240))
        else:
            cl.review_at = cl.fnol + timedelta(hours=rng.uniform(1, 30))
            cl.decided = max(cl.fnol + timedelta(days=rng.uniform(0.5, 9)), cl.review_at + timedelta(hours=rng.uniform(1, 6)))

    def _pick_policy(self, rng, weights: list[float]) -> Policy:
        return rng.choices(self._policy_list, weights=weights)[0]

    def _build_claims(self) -> None:
        rng = R(self.seed, "claims")
        self._policy_list = list(self.policies.values())
        frequent = {p.policy_number for p in rng.sample(self._policy_list, int(len(self._policy_list) * 0.08))}
        weights = [4.0 if p.policy_number in frequent else 6.0 if p.customer.fraud_prone else 1.0
                   for p in self._policy_list]
        start = datetime.combine(self.anchor, datetime.min.time()) - timedelta(days=30 * U["history_months"])
        span = (datetime.combine(self.anchor, datetime.min.time()) - start).total_seconds()
        seq = 100000
        for _ in range(U["history_claims"]):
            fnol = start + timedelta(seconds=rng.uniform(0, span - 3600))
            cl = self._claim(rng, f"CLM-{seq}", self._pick_policy(rng, weights), fnol)
            seq += 1
            self._adjudicate(rng, cl)
            self.claims.append(cl)
        for d in DATES:
            for _ in range(U["daily_claims"] + rng.randint(-5, 5)):
                fnol = datetime.combine(d, datetime.min.time()) + timedelta(seconds=rng.randint(7 * 3600, 21 * 3600))
                cl = self._claim(rng, f"CLM-{seq}", self._pick_policy(rng, weights), fnol)
                seq += 1
                self._adjudicate(rng, cl)
                self.claims.append(cl)

    def _build_telematics(self) -> None:
        rng = R(self.seed, "telematics")
        n = 0
        for cl in self.claims:
            if cl.crash_event:
                n += 1
                t = cl.incident + timedelta(seconds=rng.randint(-600, 600))
                self.crash_events.append({
                    "event_id": f"TM-{n:08d}", "vin": cl.policy.vin, "event_ts": ts(t),
                    "g_force": round(rng.uniform(2.5, 9.0), 2), "speed_kmph": round(rng.uniform(15, 95), 1),
                    "lat": round(rng.uniform(8.0, 30.0), 5), "lon": round(rng.uniform(70.0, 88.0), 5),
                    "device_id": f"DEV-{cl.policy.policy_number[-4:]}"})
        devices = [p for p in self._policy_list if p.has_telematics]
        start = datetime.combine(self.anchor, datetime.min.time()) - timedelta(days=60)
        for day in range((DATES[-1] - start.date()).days + 1):
            for _ in range(U["noise_crash_events_per_day"]):
                p = rng.choice(devices)
                n += 1
                t = start + timedelta(days=day, seconds=rng.randint(0, 86399))
                self.crash_events.append({
                    "event_id": f"TM-{n:08d}", "vin": p.vin, "event_ts": ts(t),
                    "g_force": round(rng.uniform(1.2, 3.0), 2), "speed_kmph": round(rng.uniform(5, 60), 1),
                    "lat": round(rng.uniform(8.0, 30.0), 5), "lon": round(rng.uniform(70.0, 88.0), 5),
                    "device_id": f"DEV-{p.policy_number[-4:]}"})
        self.crash_events.sort(key=lambda e: e["event_ts"])

    def _build_cdc(self) -> None:
        """Policy-admin changes on each later business date: renewals, lapses, mobile changes, NCB
        resets after a paid claim. Mutates the policies, so the current state is the last date's."""
        rng = R(self.seed, "cdc")
        self.cdc: dict[date, list[dict]] = {d: [] for d in DATES}
        book = [p for p in self.policies.values() if not p.book]
        for d in DATES[1:]:
            for p in rng.sample(book, rng.randint(4, 8)):
                kind = rng.choice(["renew", "lapse", "mobile", "ncb"])
                t = datetime.combine(d, datetime.min.time()) + timedelta(seconds=rng.randint(8 * 3600, 20 * 3600))
                if kind == "renew":
                    p.effective, p.expiry, p.status = p.expiry, p.expiry + timedelta(days=365), "ACTIVE"
                    p.premium = round(p.premium * rng.uniform(0.95, 1.1), 2)
                elif kind == "lapse":
                    p.status = "LAPSED"
                elif kind == "mobile":
                    p.customer.mobile = rng.choice("6789") + f"{rng.randint(0, 999_999_999):09d}"
                else:
                    p.ncb_pct = 0
                self.cdc[d].append({"op": "u", "ts_ms": epoch_ms(t), "policy_number": p.policy_number,
                                    "after": json.dumps(self.policy_row(p, t))})

    # ------------------------------------------------------------ records

    def policy_row(self, p: Policy, updated: datetime) -> dict:
        c = p.customer
        return {"policy_number": p.policy_number, "customer_ref": p.customer_ref, "holder_name": p.holder_name,
                "holder_dob": c.dob.strftime("%d/%m/%Y"), "holder_mobile": c.mobile, "holder_email": c.email,
                "address_city": c.city, "customer_since": c.customer_since.isoformat(), "provider_name": p.provider,
                "policy_type": "Motor", "premium_amount": f"{p.premium:.2f}", "status": p.status,
                "coverage_limit": f"{p.idv:.2f}", "deductible": f"{p.deductible:.2f}", "co_pay_pct": f"{p.co_pay_pct}",
                "waiting_period_days": "0", "effective_date": p.effective.isoformat(), "expiry_date": p.expiry.isoformat(),
                "depreciation_rate": f"{p.depreciation_rate}", "vehicle_vin": p.vin, "vehicle_reg_no": p.reg_no,
                "vehicle_make": p.make, "vehicle_model": p.model, "vehicle_year": str(p.year),
                "ncb_pct": f"{p.ncb_pct}", "zero_dep_addon": "Y" if p.zero_dep else "N",
                "rsa_addon": "Y" if p.rsa else "N", "portal_enabled": "Y" if p.book else "N", "updated_at": ts(updated)}

    def bureau_row(self, rng, c: Customer, as_of: date) -> dict:
        if c.stressed:
            credit, defaults = rng.randint(420, 599), rng.randint(1, 3)
        else:
            credit = int(max(300, min(900, rng.gauss(530 + c.care * 300, 45))))
            defaults = 1 if rng.random() < 0.03 else 0
        age = (as_of - c.dob).days // 365
        name = c.name.upper()
        if rng.random() < 0.12:
            name = f"{c.first[0]}. {c.last}".upper() if rng.random() < 0.5 else typo(rng, c.first).upper() + " " + c.last.upper()
        return {"bureau_ref": c.bureau_ref, "full_name": name, "dob": c.dob.strftime("%d/%m/%Y"),
                "mobile": "" if rng.random() < 0.05 else fmt_mobile(rng, c.mobile),
                "credit_score": str(credit), "loan_defaults_12m": str(defaults),
                "active_vehicle_loan": "Y" if rng.random() < 0.45 else "N", "driver_age": str(age),
                "years_licensed": str(max(0, min(age - 18, int(rng.gauss(c.care * 18, 4))))),
                "traffic_violations_3y": str(rng.choices([0, 1, 2, 3, 4], weights=[60 * c.care, 20, 10, 6, 4])[0]),
                "dui_history": "Y" if rng.random() < (0.06 if c.care < 0.45 else 0.01) else "N",
                "address_changed_90d": "Y" if c.address_churn or rng.random() < 0.02 else "N",
                "other_insurer_claims_3y": str(rng.randint(3, 6) if c.cross_claimant else rng.choices([0, 1, 2], weights=[75, 20, 5])[0]),
                "as_of_date": as_of.strftime("%d/%m/%Y")}

    @staticmethod
    def claim_row(cl: Claim, as_of: datetime, rng: random.Random) -> dict:
        """The claims system's view of a claim at as_of (status not yet decided stays FILED/UNDER_REVIEW)."""
        decided = cl.decided is not None and cl.decided <= as_of
        status = cl.status if decided else ("UNDER_REVIEW" if cl.review_at and cl.review_at <= as_of else "FILED")
        c = cl.policy.customer
        name = c.name if rng.random() < 0.8 else typo(rng, c.first) + " " + c.last
        return {"claim_id": cl.claim_id, "policy_number": cl.policy.policy_number, "claimant_name": name,
                "claimant_mobile": fmt_mobile(rng, c.mobile), "claim_type": cl.claim_type,
                "incident_ts": ts(cl.incident), "fnol_ts": ts(cl.fnol), "incident_city": cl.city,
                "amount_requested": round(cl.amount, 2), "vehicle_vin": cl.stated_vin, "garage_id": cl.garage_id,
                "police_report": "Y" if cl.police_report else "N", "third_party_involved": "Y" if cl.third_party else "N",
                "channel": cl.channel, "status": status,
                "amount_approved": cl.amount_approved if decided else None,
                "decided_ts": ts(cl.decided) if decided else None, "decided_by": cl.decided_by if decided else None,
                "reason_code": cl.reason_code if decided else None}

    @staticmethod
    def status_events(cl: Claim) -> list[tuple[datetime, dict]]:
        out = []
        if cl.review_at:
            out.append((cl.review_at, {"claim_id": cl.claim_id, "event_ts": ts(cl.review_at), "from_status": "FILED",
                                       "to_status": "UNDER_REVIEW", "amount_approved": None, "reason_code": None,
                                       "decided_by": None}))
        if cl.decided:
            out.append((cl.decided, {"claim_id": cl.claim_id, "event_ts": ts(cl.decided),
                                     "from_status": "UNDER_REVIEW" if cl.review_at else "FILED",
                                     "to_status": cl.status, "amount_approved": cl.amount_approved,
                                     "reason_code": cl.reason_code, "decided_by": cl.decided_by}))
        return out

    def truth(self) -> dict:
        """What the generator knows and the lakehouse must rediscover: identities and labels."""
        return {"customers": {c.customer_ref: {"bureau_ref": c.bureau_ref, "email": c.email,
                                               "customer_refs": sorted({p.customer_ref for p in c.policies}),
                                               "policies": [p.policy_number for p in c.policies]}
                              for c in self.customers},
                "fraud_claims": sorted(cl.claim_id for cl in self.claims if cl.fraud)}
