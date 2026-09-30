"""Column specs and validators for the silver tables.

docs/ARCHITECTURE.md is the source of truth; change it first, then this file.

Each validator checks required columns, dtypes, nulls in non-nullable columns, key
uniqueness, allowed values and point-in-time rules. Errors report column names and
counts only, never row values (CI logs are public).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from pandas.api import types as ptypes

# dtype kinds
STR, INT, FLOAT, BOOL, DATE, TS = "str", "int", "float", "bool", "date", "timestamp"


class SchemaError(ValueError):
    """A dataframe violates its table contract."""

    def __init__(self, table: str, problems: list[str]):
        self.table = table
        self.problems = problems
        super().__init__(f"{table}: " + "; ".join(problems))


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    nullable: bool = False
    allowed: frozenset[str] | None = None


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[Column, ...]
    key: tuple[str, ...]
    ordered_pairs: tuple[tuple[str, str], ...] = field(default=())  # (earlier, later): earlier <= later
    strict_pairs: tuple[tuple[str, str], ...] = field(default=())   # earlier < later

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


def _c(name, kind, nullable=False, allowed=None):
    return Column(name, kind, nullable, frozenset(allowed) if allowed else None)


SECURITY_MASTER = TableSpec(
    "security_master",
    (_c("security_id", STR), _c("cik", STR, True), _c("figi", STR, True), _c("name", STR),
     _c("security_type", STR), _c("exchange", STR, True), _c("first_seen", DATE),
     _c("last_seen", DATE, True)),
    key=("security_id",),
    ordered_pairs=(("first_seen", "last_seen"),),
)

TICKER_HISTORY = TableSpec(
    "ticker_history",
    (_c("security_id", STR), _c("ticker", STR), _c("valid_from", DATE),
     _c("valid_to", DATE, True)),
    key=("security_id", "valid_from"),
    ordered_pairs=(("valid_from", "valid_to"),),
)

PRICES_DAILY = TableSpec(
    "prices_daily",
    (_c("date", DATE), _c("security_id", STR), _c("open", FLOAT), _c("high", FLOAT),
     _c("low", FLOAT), _c("close", FLOAT), _c("volume", INT), _c("dollar_volume", FLOAT),
     _c("n_sources", INT), _c("agree_flag", BOOL), _c("primary_source", STR),
     _c("flags", STR, True)),
    key=("date", "security_id"),
)

CORPORATE_ACTIONS = TableSpec(
    "corporate_actions",
    (_c("security_id", STR), _c("ex_date", DATE),
     _c("action", STR, allowed={"split", "cash_dividend", "spinoff"}), _c("value", FLOAT),
     _c("source", STR), _c("n_sources", INT)),
    key=("security_id", "ex_date", "action"),
)

TOTAL_RETURN_DAILY = TableSpec(
    "total_return_daily",
    (_c("date", DATE), _c("security_id", STR), _c("ret_1d", FLOAT, True),
     _c("adj_factor", FLOAT)),
    key=("date", "security_id"),
)

UNIVERSE_MEMBERSHIP = TableSpec(
    "universe_membership",
    (_c("date", DATE), _c("security_id", STR), _c("in_sp500", BOOL), _c("source_agree", BOOL)),
    key=("date", "security_id"),
)

DELISTINGS = TableSpec(
    "delistings",
    (_c("security_id", STR), _c("last_date", DATE),
     _c("reason", STR, allowed={"acquired", "bankrupt", "moved", "unknown"}),
     _c("delisting_return", FLOAT, True), _c("observed", BOOL)),
    key=("security_id",),
)

FUNDAMENTALS_PIT = TableSpec(
    "fundamentals_pit",
    (_c("security_id", STR), _c("concept", STR), _c("value", FLOAT), _c("period_end", DATE),
     _c("filed", DATE), _c("available_from", DATE)),
    key=("security_id", "concept", "period_end", "filed"),
    ordered_pairs=(("period_end", "filed"),),
    strict_pairs=(("filed", "available_from"),),  # available_from = next trading day after filed
)

MACRO_DAILY = TableSpec(
    "macro_daily",
    (_c("date", DATE), _c("series", STR), _c("value", FLOAT, True), _c("vintage", DATE)),
    key=("date", "series", "vintage"),
    ordered_pairs=(("date", "vintage"),),  # a value cannot be published before its date
)

SILVER_TABLES: dict[str, TableSpec] = {
    t.name: t for t in (SECURITY_MASTER, TICKER_HISTORY, PRICES_DAILY, CORPORATE_ACTIONS,
                        TOTAL_RETURN_DAILY, UNIVERSE_MEMBERSHIP, DELISTINGS,
                        FUNDAMENTALS_PIT, MACRO_DAILY)
}


def _kind_ok(s: pd.Series, kind: str) -> bool:
    if kind == STR:
        return ptypes.is_string_dtype(s) or (ptypes.is_object_dtype(s) and
                                             s.dropna().map(type).eq(str).all())
    if kind == INT:
        return ptypes.is_integer_dtype(s) and not ptypes.is_bool_dtype(s)
    if kind == FLOAT:
        return ptypes.is_float_dtype(s) or (ptypes.is_integer_dtype(s) and not ptypes.is_bool_dtype(s))
    if kind == BOOL:
        return ptypes.is_bool_dtype(s)
    if kind == DATE:
        return ptypes.is_datetime64_dtype(s) and not isinstance(s.dtype, pd.DatetimeTZDtype)
    if kind == TS:
        return isinstance(s.dtype, pd.DatetimeTZDtype) and str(s.dtype.tz) == "UTC"
    raise ValueError(f"unknown kind {kind!r}")


def require_columns(df: pd.DataFrame, columns: list[str] | tuple[str, ...], table: str = "frame") -> None:
    """Raise SchemaError if any required column is missing."""
    if not isinstance(df, pd.DataFrame):
        raise SchemaError(table, ["input is not a DataFrame"])
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SchemaError(table, [f"missing columns {missing}"])


def check_point_in_time(df: pd.DataFrame, date_col: str = "date",
                        available_col: str = "available_from", table: str = "frame") -> None:
    """Raise if any row uses information not yet available: available_from must be <= date."""
    require_columns(df, [date_col, available_col], table)
    bad = int((df[available_col] > df[date_col]).sum())
    if bad:
        raise SchemaError(table, [f"{bad} rows with {available_col} > {date_col}"])


def validate(df: pd.DataFrame, spec: TableSpec) -> pd.DataFrame:
    """Validate df against spec. Returns df unchanged; raises SchemaError listing all problems."""
    require_columns(df, spec.column_names, spec.name)
    problems: list[str] = []

    for col in spec.columns:
        s = df[col.name]
        if not _kind_ok(s, col.kind):
            problems.append(f"{col.name}: dtype {s.dtype} is not {col.kind}")
        n_null = int(s.isna().sum())
        if n_null and not col.nullable:
            problems.append(f"{col.name}: {n_null} nulls in non-nullable column")
        if col.allowed is not None:
            n_bad = int((~s.dropna().isin(col.allowed)).sum())
            if n_bad:
                problems.append(f"{col.name}: {n_bad} values outside {sorted(col.allowed)}")

    n_dup = int(df.duplicated(list(spec.key)).sum())
    if n_dup:
        problems.append(f"key {list(spec.key)}: {n_dup} duplicate rows")

    for earlier, later in spec.ordered_pairs:
        n_bad = int((df[earlier] > df[later]).sum())  # NaT compares False
        if n_bad:
            problems.append(f"{n_bad} rows with {earlier} > {later}")
    for earlier, later in spec.strict_pairs:
        n_bad = int((df[earlier] >= df[later]).sum())
        if n_bad:
            problems.append(f"{n_bad} rows with {earlier} >= {later}")

    if problems:
        raise SchemaError(spec.name, problems)
    return df


def validate_table(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Validate df against the silver table named table."""
    if table not in SILVER_TABLES:
        raise KeyError(f"unknown table {table!r}")
    return validate(df, SILVER_TABLES[table])
