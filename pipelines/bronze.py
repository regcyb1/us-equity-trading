"""Keyed, idempotent, never-shrinking bronze parquet writes.

Layout: <root>/bronze/<table>/<partition>.parquet. Rewriting a partition is allowed only
if every existing key is still present; otherwise ShrinkError. Identical content is a
no-op. Writes go to a temp file and are renamed into place.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


class ShrinkError(RuntimeError):
    """A write would remove keys already stored."""


class DuplicateKeyError(ValueError):
    pass


def partition_path(root: Path | str, table: str, partition: str) -> Path:
    if not table or "/" in table or "/" in partition or partition.startswith("."):
        raise ValueError("invalid table or partition name")
    return Path(root) / "bronze" / table / f"{partition}.parquet"


def read_partition(root: Path | str, table: str, partition: str) -> pd.DataFrame | None:
    path = partition_path(root, table, partition)
    return pd.read_parquet(path) if path.exists() else None


def _keys(df: pd.DataFrame, key: tuple[str, ...]) -> pd.MultiIndex:
    return pd.MultiIndex.from_frame(df[list(key)].astype(str))


def write_partition(df: pd.DataFrame, root: Path | str, table: str, partition: str,
                    key: tuple[str, ...]) -> str:
    """Write df as one partition. Returns 'created', 'replaced' or 'unchanged'."""
    missing = [c for c in key if c not in df.columns]
    if missing:
        raise ValueError(f"{table}: missing key columns {missing}")
    n_dup = int(df.duplicated(list(key)).sum())
    if n_dup:
        raise DuplicateKeyError(f"{table}/{partition}: {n_dup} duplicate keys")

    path = partition_path(root, table, partition)
    df = df.sort_values(list(key)).reset_index(drop=True)
    status = "created"
    if path.exists():
        old = pd.read_parquet(path)
        lost = len(_keys(old, key).difference(_keys(df, key)))
        if lost:
            raise ShrinkError(f"{table}/{partition}: write would drop {lost} existing keys")
        old = old.sort_values(list(key)).reset_index(drop=True)
        if list(old.columns) == list(df.columns) and old.equals(df):
            return "unchanged"
        status = "replaced"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return status


def latest_partition_before(root: Path | str, table: str, partition: str) -> str | None:
    """Name of the newest partition that sorts before partition (names are ISO-dated)."""
    folder = Path(root) / "bronze" / table
    if not folder.exists():
        return None
    names = sorted(p.stem for p in folder.glob("*.parquet") if p.stem < partition)
    return names[-1] if names else None
