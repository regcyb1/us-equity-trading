import pandas as pd
import pytest

from contracts import schema
from contracts.registries import FEATURE_REGISTRY
from tests.fixtures import silver


def test_every_silver_table_has_fixture():
    assert set(silver.ALL) == set(schema.SILVER_TABLES)


@pytest.mark.parametrize("table", sorted(schema.SILVER_TABLES))
def test_valid_fixture_passes(table):
    df = silver.ALL[table]()
    assert schema.validate_table(df, table) is df


@pytest.mark.parametrize("table", sorted(schema.SILVER_TABLES))
def test_missing_required_column(table):
    spec = schema.SILVER_TABLES[table]
    df = silver.ALL[table]().drop(columns=[spec.key[0]])
    with pytest.raises(schema.SchemaError, match="missing columns"):
        schema.validate(df, spec)


@pytest.mark.parametrize("table", sorted(schema.SILVER_TABLES))
def test_duplicate_key(table):
    df = silver.ALL[table]()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(schema.SchemaError, match="duplicate"):
        schema.validate_table(df, table)


def test_wrong_dtypes():
    df = silver.prices_daily()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["volume"] = df["volume"].astype(float)
    df["agree_flag"] = df["agree_flag"].astype(int)
    with pytest.raises(schema.SchemaError) as e:
        schema.validate_table(df, "prices_daily")
    msg = str(e.value)
    assert "date: dtype" in msg and "volume: dtype" in msg and "agree_flag: dtype" in msg


def test_tz_aware_date_rejected():
    df = silver.prices_daily()
    df["date"] = df["date"].dt.tz_localize("UTC")
    with pytest.raises(schema.SchemaError, match="date: dtype"):
        schema.validate_table(df, "prices_daily")


def test_null_in_non_nullable():
    df = silver.prices_daily()
    df.loc[0, "close"] = None
    with pytest.raises(schema.SchemaError, match="close: 1 nulls"):
        schema.validate_table(df, "prices_daily")


def test_allowed_values():
    df = silver.corporate_actions()
    df.loc[0, "action"] = "merger"
    with pytest.raises(schema.SchemaError, match="action: 1 values outside"):
        schema.validate_table(df, "corporate_actions")


def test_fundamentals_available_from_must_follow_filed():
    df = silver.fundamentals_pit()
    df.loc[0, "available_from"] = df.loc[0, "filed"]
    with pytest.raises(schema.SchemaError, match="filed >= available_from"):
        schema.validate_table(df, "fundamentals_pit")


def test_fundamentals_filed_before_period_end_rejected():
    df = silver.fundamentals_pit()
    df.loc[0, "filed"] = pd.Timestamp("2026-03-01")
    with pytest.raises(schema.SchemaError, match="period_end > filed"):
        schema.validate_table(df, "fundamentals_pit")


def test_ticker_validity_range_ordered():
    df = silver.ticker_history()
    df.loc[0, "valid_to"] = pd.Timestamp("2019-01-01")
    with pytest.raises(schema.SchemaError, match="valid_from > valid_to"):
        schema.validate_table(df, "ticker_history")


def test_point_in_time_join_check():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-04", "2026-05-01"]),
        "available_from": pd.to_datetime(["2026-05-04", "2026-05-04"]),
    })
    schema.check_point_in_time(df.iloc[[0]])
    with pytest.raises(schema.SchemaError, match="1 rows with available_from > date"):
        schema.check_point_in_time(df)


def test_errors_report_counts_not_values():
    df = silver.prices_daily()
    df.loc[0, "security_id"] = None
    df.loc[1, "close"] = None
    with pytest.raises(schema.SchemaError) as e:
        schema.validate_table(df, "prices_daily")
    msg = str(e.value)
    for value in ("S000002", "20.2", "S000001"):
        assert value not in msg


def test_non_dataframe_rejected():
    with pytest.raises(schema.SchemaError, match="not a DataFrame"):
        schema.validate_table([{"date": 1}], "prices_daily")


def test_unknown_table():
    with pytest.raises(KeyError):
        schema.validate_table(pd.DataFrame(), "nope")


def test_feature_registry_starts_empty():
    assert FEATURE_REGISTRY == {}
