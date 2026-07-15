"""
Generate a synthetic messy .xlsx for testing the full pipeline.

Deliberately includes:
  * mixed-type columns (numbers stored as strings, stray text)
  * missing values + a variety of placeholder tokens ("N/A", "-", "?", "unknown", "")
  * a heavily right-skewed numeric column with a couple of extreme outliers
    -> designed so a naive fill_mean choice is wrong and the Verifier should
       push the Cleaner toward fill_median (exercises the revision loop)
  * a categorical column with inconsistent casing/whitespace
  * a boolean-ish column with mixed tokens
  * a date column stored as strings with mixed formats

Run:  python sample_data/generate_messy_sample.py
"""

from __future__ import annotations

import os
import random

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
random.seed(42)

N = 200


def _inject_placeholders(values, tokens, rate):
    out = []
    for v in values:
        if random.random() < rate:
            out.append(random.choice(tokens))
        else:
            out.append(v)
    return out


def build() -> pd.DataFrame:
    # age: integer-ish but stored with some placeholders and as mixed types
    age = RNG.integers(18, 70, size=N).astype(object)
    age = _inject_placeholders(list(age), ["N/A", "", "unknown", "-"], 0.12)

    # income: heavily right-skewed + extreme outliers -> median is correct.
    income = RNG.lognormal(mean=10.5, sigma=0.6, size=N)
    income[:3] = [5_000_000, 8_500_000, 12_000_000]  # billionaire-style outliers
    income = np.round(income, 2).astype(object)
    income = _inject_placeholders(list(income), ["?", "", "N/A"], 0.08)

    # score: roughly symmetric numeric with some missing -> mean is fine.
    score = np.round(RNG.normal(70, 10, size=N), 1).astype(object)
    score = _inject_placeholders(list(score), ["", "null"], 0.10)

    # city: inconsistent casing + whitespace + placeholders.
    raw_cities = ["mumbai", "MUMBAI", " Delhi", "delhi ", "Bangalore", "bangalore",
                  "Chennai", "CHENNAI ", "kolkata"]
    city = [random.choice(raw_cities) for _ in range(N)]
    city = _inject_placeholders(city, ["unknown", "", "-"], 0.10)

    # is_active: boolean stored as mixed tokens.
    bool_tokens = ["Yes", "no", "TRUE", "false", "Y", "N", "1", "0"]
    is_active = [random.choice(bool_tokens) for _ in range(N)]
    is_active = _inject_placeholders(is_active, ["", "N/A"], 0.08)

    # signup_date: dates as strings, mixed formats + placeholders.
    base = pd.Timestamp("2021-01-01")
    dates = [(base + pd.Timedelta(days=int(RNG.integers(0, 1200)))) for _ in range(N)]
    fmts = ["%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y"]
    signup = [d.strftime(random.choice(fmts)) for d in dates]
    signup = _inject_placeholders(signup, ["", "unknown", "N/A"], 0.10)

    # notes: mostly-missing free text (>50% missing) -> should be left_null/dropped.
    notes = _inject_placeholders(
        ["follow up", "vip", "priority", "checked"] * (N // 4 + 1),
        ["", "-", "N/A"], 0.75,
    )[:N]

    # a numeric column with almost no signal but stored as strings
    ref_id = [f"{RNG.integers(1000, 9999)}" for _ in range(N)]

    return pd.DataFrame(
        {
            "age": age,
            "income": income,
            "score": score,
            "city": city,
            "is_active": is_active,
            "signup_date": signup,
            "notes": notes,
            "ref_id": ref_id,
        }
    )


def main():
    df = build()
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, "messy_sample.xlsx")
    df.to_excel(out_path, index=False)
    print(f"Wrote {out_path}  ({df.shape[0]} rows x {df.shape[1]} cols)")
    print(df.head(8).to_string())


if __name__ == "__main__":
    main()
