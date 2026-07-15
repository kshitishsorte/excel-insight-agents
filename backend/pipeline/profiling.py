"""
Deterministic per-column profiling (pure pandas/numpy — NO LLM).

The profile, not the raw dataframe, is what gets sent to the Correction and
Verifier agents. This keeps prompts small and keeps raw PII out of the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np
import pandas as pd

import config


@dataclass
class ColumnProfile:
    name: str
    current_dtype: str
    n_total: int
    n_missing: int                      # native NaN/None only
    pct_missing: float                  # includes detected placeholders
    n_unique: int
    sample_values: list[Any] = field(default_factory=list)
    placeholder_tokens_found: list[str] = field(default_factory=list)
    n_placeholder: int = 0
    looks_numeric: bool = False
    # Numeric-only stats (None when not applicable)
    numeric_min: Optional[float] = None
    numeric_max: Optional[float] = None
    numeric_mean: Optional[float] = None
    numeric_median: Optional[float] = None
    numeric_mode: Optional[float] = None
    skewness: Optional[float] = None
    n_outliers: int = 0
    outlier_flag: bool = False
    # Categorical hint
    looks_datetime: bool = False
    looks_boolean: bool = False
    # Case/whitespace variants: how many distinct values collapse when
    # trimmed + case-folded (e.g. "DELHI", "delhi", " Delhi " -> one value).
    n_unique_normalized: int = 0
    n_case_variants: int = 0            # n_unique - n_unique_normalized
    case_variant_examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    s = str(value).strip().lower()
    return s in config.PLACEHOLDER_TOKENS


def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Try to read a (possibly string) series as numbers, ignoring placeholders."""
    cleaned = series.map(lambda v: np.nan if _is_placeholder(v) else v)
    return pd.to_numeric(cleaned, errors="coerce")


def _looks_datetime(series: pd.Series, non_missing: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if non_missing.empty:
        return False
    sample = non_missing.astype(str).head(50)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    ratio = parsed.notna().mean()
    # Guard against pure-integer columns being read as epoch datetimes.
    numeric_ratio = pd.to_numeric(sample, errors="coerce").notna().mean()
    return ratio >= 0.8 and numeric_ratio < 0.8


def _looks_boolean(non_missing_str_lower: pd.Series) -> bool:
    if non_missing_str_lower.empty:
        return False
    bool_tokens = {"true", "false", "yes", "no", "y", "n", "0", "1", "t", "f"}
    uniq = set(non_missing_str_lower.unique())
    return uniq.issubset(bool_tokens) and len(uniq) <= 3 and len(uniq) >= 1


def profile_column(series: pd.Series) -> ColumnProfile:
    name = str(series.name)
    n_total = len(series)

    # Native missing.
    native_missing_mask = series.isna()
    n_missing = int(native_missing_mask.sum())

    # Placeholder detection on the non-native-missing values.
    placeholder_mask = series.map(_is_placeholder) & ~native_missing_mask
    n_placeholder = int(placeholder_mask.sum())
    placeholders_found = sorted(
        {
            str(v).strip()
            for v in series[placeholder_mask].unique()
        }
    )[:10]

    effective_missing = native_missing_mask | series.map(_is_placeholder)
    pct_missing = float(effective_missing.mean()) if n_total else 0.0

    non_missing = series[~effective_missing]
    n_unique = int(non_missing.nunique())

    sample_values = [
        _jsonable(v) for v in non_missing.head(config.SAMPLE_VALUES_PER_COLUMN).tolist()
    ]

    prof = ColumnProfile(
        name=name,
        current_dtype=str(series.dtype),
        n_total=n_total,
        n_missing=n_missing,
        pct_missing=round(pct_missing, 4),
        n_unique=n_unique,
        sample_values=sample_values,
        placeholder_tokens_found=placeholders_found,
        n_placeholder=n_placeholder,
    )

    # Numeric analysis (works even for numeric-looking strings).
    numeric = _coerce_numeric(series)
    numeric_valid = numeric.dropna()
    numeric_ratio = (len(numeric_valid) / len(non_missing)) if len(non_missing) else 0.0
    prof.looks_numeric = bool(numeric_ratio >= 0.9 and len(numeric_valid) > 0)

    if prof.looks_numeric:
        prof.numeric_min = _f(numeric_valid.min())
        prof.numeric_max = _f(numeric_valid.max())
        prof.numeric_mean = _f(numeric_valid.mean())
        prof.numeric_median = _f(numeric_valid.median())
        mode_vals = numeric_valid.mode()
        prof.numeric_mode = _f(mode_vals.iloc[0]) if not mode_vals.empty else None
        if len(numeric_valid) >= 3:
            prof.skewness = _f(numeric_valid.skew())
        # IQR outliers.
        q1, q3 = numeric_valid.quantile(0.25), numeric_valid.quantile(0.75)
        iqr = q3 - q1
        if iqr > 0:
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = ((numeric_valid < low) | (numeric_valid > high)).sum()
            prof.n_outliers = int(outliers)
            prof.outlier_flag = bool(outliers > 0)

    # Type hints for non-numeric columns.
    non_missing_str_lower = non_missing.astype(str).str.strip().str.lower()
    if not prof.looks_numeric:
        prof.looks_datetime = bool(_looks_datetime(series, non_missing))
        prof.looks_boolean = bool(_looks_boolean(non_missing_str_lower))

        # Detect case/whitespace variants (e.g. "DELHI" vs "delhi" vs " Delhi ").
        norm = non_missing_str_lower
        prof.n_unique_normalized = int(norm.nunique())
        prof.n_case_variants = max(0, n_unique - prof.n_unique_normalized)
        if prof.n_case_variants > 0:
            examples: list[str] = []
            stripped = non_missing.astype(str).str.strip()
            for key, grp in stripped.groupby(norm):
                variants = sorted(set(grp.tolist()))
                if len(variants) > 1:
                    examples.append(" / ".join(variants[:4]))
                if len(examples) >= 3:
                    break
            prof.case_variant_examples = examples

    return prof


def profile_dataframe(df: pd.DataFrame) -> list[ColumnProfile]:
    if len(df) > config.MAX_ROWS_FOR_PROFILING:
        df = df.sample(config.MAX_ROWS_FOR_PROFILING, random_state=0)
    return [profile_column(df[col]) for col in df.columns]


def profile_for_llm(profile: ColumnProfile) -> dict:
    """Compact dict of the fields the LLM needs (drops noisy internals)."""
    d = {
        "name": str(profile.name),
        "current_dtype": profile.current_dtype,
        "pct_missing": profile.pct_missing,
        "n_unique": int(profile.n_unique),
        "n_total": int(profile.n_total),
        "sample_values": profile.sample_values,
        "placeholder_tokens_found": profile.placeholder_tokens_found,
        "looks_numeric": bool(profile.looks_numeric),
        "looks_datetime": bool(profile.looks_datetime),
        "looks_boolean": bool(profile.looks_boolean),
    }
    if profile.n_case_variants > 0:
        d["case_variants"] = int(profile.n_case_variants)
        d["case_variant_examples"] = profile.case_variant_examples
    if profile.looks_numeric:
        d.update(
            {
                "min": profile.numeric_min,
                "max": profile.numeric_max,
                "mean": profile.numeric_mean,
                "median": profile.numeric_median,
                "mode": profile.numeric_mode,
                "skewness": profile.skewness,
                "n_outliers": profile.n_outliers,
            }
        )
    return d


# --- small helpers -----------------------------------------------------------
def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(v, (pd.Timestamp,)):
        return str(v)
    if v is None:
        return None
    return str(v) if not isinstance(v, (int, float, bool, str)) else v
