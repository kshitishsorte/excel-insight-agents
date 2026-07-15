"""
Excel upload loading/validation and cleaned-file export.
"""

from __future__ import annotations

import io
from typing import Optional

import pandas as pd


class ExcelLoadError(ValueError):
    """Raised for unsupported / unreadable / empty uploads."""


def _rewind(file_like) -> None:
    """Reset a buffer to the start so it can be re-read (Streamlit UploadedFile)."""
    try:
        file_like.seek(0)
    except (AttributeError, OSError):
        pass  # a path string has no seek; that's fine


def list_sheets(file_like) -> list[str]:
    """Return sheet names without loading all data. Accepts a path or buffer."""
    _rewind(file_like)
    try:
        xls = pd.ExcelFile(file_like)
        return xls.sheet_names
    except Exception as exc:  # noqa: BLE001
        raise ExcelLoadError(f"Could not read the workbook: {exc}") from exc


def load_sheet(file_like, sheet_name: Optional[str] = None) -> pd.DataFrame:
    """Load one sheet into a dataframe, with basic validation."""
    _rewind(file_like)
    try:
        df = pd.read_excel(file_like, sheet_name=sheet_name)
    except Exception as exc:  # noqa: BLE001
        raise ExcelLoadError(f"Could not read the selected sheet: {exc}") from exc

    if isinstance(df, dict):  # sheet_name=None returns a dict
        # Take the first non-empty sheet.
        for name, frame in df.items():
            if not frame.empty:
                df = frame
                break
        else:
            raise ExcelLoadError("The workbook has no non-empty sheets.")

    if df is None or df.shape[0] == 0 or df.shape[1] == 0:
        raise ExcelLoadError("The selected sheet is empty (no rows or no columns).")

    # Drop fully-empty columns/rows that Excel often leaves behind.
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    if df.shape[0] == 0 or df.shape[1] == 0:
        raise ExcelLoadError("The selected sheet has no usable data.")

    # Normalise column names to strings.
    df.columns = [str(c) for c in df.columns]
    return df.reset_index(drop=True)


def dataframe_to_xlsx_bytes(df: pd.DataFrame, sheet_name: str = "cleaned") -> bytes:
    """Serialize a dataframe to .xlsx bytes for download."""
    buf = io.BytesIO()
    safe_name = (sheet_name or "cleaned")[:31]  # Excel sheet-name limit
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=safe_name)
    return buf.getvalue()
