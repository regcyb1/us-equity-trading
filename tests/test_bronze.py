import pandas as pd
import pytest

from pipelines import bronze

KEY = ("date", "ticker")


def frame(tickers, close=1.0):
    return pd.DataFrame({"date": pd.Timestamp("2026-09-30"), "ticker": tickers,
                         "close": close})


def test_create_unchanged_replace(tmp_path):
    assert bronze.write_partition(frame(["A", "B"]), tmp_path, "t", "date=2026-09-30", KEY) == "created"
    assert bronze.write_partition(frame(["B", "A"]), tmp_path, "t", "date=2026-09-30", KEY) == "unchanged"
    assert bronze.write_partition(frame(["A", "B", "C"]), tmp_path, "t", "date=2026-09-30", KEY) == "replaced"
    assert len(bronze.read_partition(tmp_path, "t", "date=2026-09-30")) == 3


def test_shrink_raises_and_keeps_old(tmp_path):
    bronze.write_partition(frame(["A", "B"]), tmp_path, "t", "p", KEY)
    with pytest.raises(bronze.ShrinkError, match="drop 1"):
        bronze.write_partition(frame(["A"]), tmp_path, "t", "p", KEY)
    assert len(bronze.read_partition(tmp_path, "t", "p")) == 2


def test_duplicate_keys_rejected(tmp_path):
    with pytest.raises(bronze.DuplicateKeyError):
        bronze.write_partition(frame(["A", "A"]), tmp_path, "t", "p", KEY)


def test_bad_names_rejected(tmp_path):
    with pytest.raises(ValueError):
        bronze.write_partition(frame(["A"]), tmp_path, "../t", "p", KEY)


def test_latest_partition_before(tmp_path):
    for d in ("date=2026-09-28", "date=2026-09-29", "date=2026-09-30"):
        bronze.write_partition(frame(["A"]), tmp_path, "t", d, KEY)
    assert bronze.latest_partition_before(tmp_path, "t", "date=2026-09-30") == "date=2026-09-29"
    assert bronze.latest_partition_before(tmp_path, "t", "date=2026-09-28") is None
    assert bronze.latest_partition_before(tmp_path, "missing", "x") is None
