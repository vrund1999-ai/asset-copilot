"""Synthetic portfolio generator. Fully synthetic: no confidential or real property data.

Usage:  python -m asset_copilot.synth.generate --properties 60 --seed 42
"""

import argparse
import random
from datetime import date, timedelta

from faker import Faker
from sqlalchemy import text

from ..db import admin_engine

ASSET_TYPES = {
    # type: (sq_ft range, rent psf range, tenants per property, opex ratio)
    "logistics": ((150_000, 900_000), (6, 14), (1, 4), 0.20),
    "multifamily": ((120_000, 450_000), (24, 48), (40, 120), 0.38),
    "office": ((100_000, 700_000), (35, 85), (5, 25), 0.45),
    "hospitality": ((80_000, 400_000), (40, 90), (1, 3), 0.62),
}
MARKETS = [("Dallas", "TX"), ("Phoenix", "AZ"), ("Atlanta", "GA"), ("Chicago", "IL"),
           ("New York", "NY"), ("Miami", "FL"), ("Denver", "CO"), ("Seattle", "WA")]
INDUSTRIES = ["Logistics", "Retail", "Technology", "Healthcare", "Finance", "Manufacturing"]


def generate(n_properties: int, seed: int) -> None:
    rnd = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)
    today = date.today()
    engine = admin_engine()

    with engine.begin() as conn:
        for table in ["feedback", "audit_log", "document_chunks", "documents", "debt",
                      "budgets", "operating_statements", "leases", "tenants", "properties"]:
            conn.execute(text(f"TRUNCATE {table} RESTART IDENTITY CASCADE"))

        for _ in range(n_properties):
            asset_type = rnd.choice(list(ASSET_TYPES))
            (sf_lo, sf_hi), (r_lo, r_hi), (t_lo, t_hi), opex_ratio = ASSET_TYPES[asset_type]
            city, state = rnd.choice(MARKETS)
            sq_ft = rnd.randint(sf_lo, sf_hi)
            acquired = today - timedelta(days=rnd.randint(200, 2500))
            avg_rent = rnd.uniform(r_lo, r_hi)
            price = round(sq_ft * avg_rent * rnd.uniform(11, 16), 2)

            pid = conn.execute(
                text("INSERT INTO properties (name, asset_type, city, state, sq_ft, year_built, "
                     "acquired_on, purchase_price) VALUES (:n,:t,:c,:s,:sf,:y,:a,:p) "
                     "RETURNING property_id"),
                {"n": f"{fake.last_name()} {asset_type.title()} {city}", "t": asset_type,
                 "c": city, "s": state, "sf": sq_ft, "y": rnd.randint(1985, 2022),
                 "a": acquired, "p": price},
            ).scalar_one()

            # Leases
            n_tenants = rnd.randint(t_lo, t_hi)
            per_lease_sf = sq_ft * rnd.uniform(0.85, 0.97) / n_tenants
            annual_rent = 0.0
            for i in range(n_tenants):
                tid = conn.execute(
                    text("INSERT INTO tenants (name, industry) VALUES (:n,:i) RETURNING tenant_id"),
                    {"n": fake.company(), "i": rnd.choice(INDUSTRIES)},
                ).scalar_one()
                start = today - timedelta(days=rnd.randint(30, 1800))
                term_years = 1 if asset_type == "multifamily" else rnd.randint(3, 12)
                end = start + timedelta(days=365 * term_years)
                rent_psf = round(avg_rent * rnd.uniform(0.9, 1.1), 2)
                lease_sf = int(per_lease_sf)
                annual_rent += rent_psf * lease_sf
                conn.execute(
                    text("INSERT INTO leases (property_id, tenant_id, suite, leased_sq_ft, "
                         "start_date, end_date, base_rent_psf, annual_escalation, renewal_options) "
                         "VALUES (:p,:t,:s,:sf,:st,:en,:r,:e,:o)"),
                    {"p": pid, "t": tid, "s": f"Suite {i + 1}", "sf": lease_sf, "st": start,
                     "en": end, "r": rent_psf, "e": rnd.choice([0.025, 0.03, 0.035]),
                     "o": rnd.choice([0, 1, 2])},
                )

            # 24 months of actuals + budget
            monthly_rev = annual_rent / 12
            for m in range(24):
                month = (today.replace(day=1) - timedelta(days=30 * m)).replace(day=1)
                b_rev = monthly_rev * rnd.uniform(0.98, 1.02)
                b_opex = b_rev * opex_ratio
                a_rev = b_rev * rnd.uniform(0.93, 1.05)
                a_opex = b_opex * rnd.uniform(0.92, 1.10)
                for tbl, rev, ox in (("budgets", b_rev, b_opex),
                                     ("operating_statements", a_rev, a_opex)):
                    conn.execute(
                        text(f"INSERT INTO {tbl} (property_id, month, revenue, opex) "
                             "VALUES (:p,:m,:r,:o)"),
                        {"p": pid, "m": month, "r": round(rev, 2), "o": round(ox, 2)},
                    )

            # Debt
            conn.execute(
                text("INSERT INTO debt (property_id, lender, principal, rate, maturity_date) "
                     "VALUES (:p,:l,:pr,:r,:m)"),
                {"p": pid, "l": fake.company() + " Bank", "pr": round(price * rnd.uniform(0.5, 0.7), 2),
                 "r": round(rnd.uniform(0.045, 0.085), 4),
                 "m": today + timedelta(days=rnd.randint(180, 365 * 7))},
            )
    print(f"Generated {n_properties} properties (seed={seed}).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--properties", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    generate(args.properties, args.seed)
