"""Synthetic, valid silver-table frames. Identifiers and values are made up."""

import pandas as pd

D = pd.to_datetime


def security_master():
    return pd.DataFrame({
        "security_id": ["S000001", "S000002"],
        "cik": ["0000000001", None],
        "figi": ["BBG000FAKE01", None],
        "name": ["Alpha Test Corp", "Beta Test Inc"],
        "security_type": ["common", "ETF"],
        "exchange": ["XNYS", "XNAS"],
        "first_seen": D(["2020-01-02", "2021-03-01"]),
        "last_seen": D(["2026-09-29", None]),
    })


def ticker_history():
    return pd.DataFrame({
        "security_id": ["S000001", "S000001", "S000002"],
        "ticker": ["AAA", "AAB", "BBB"],
        "valid_from": D(["2020-01-02", "2023-06-01", "2021-03-01"]),
        "valid_to": D(["2023-05-31", None, None]),
    })


def prices_daily():
    return pd.DataFrame({
        "date": D(["2026-09-28", "2026-09-28", "2026-09-29"]),
        "security_id": ["S000001", "S000002", "S000001"],
        "open": [10.0, 20.0, 10.5], "high": [11.0, 21.0, 11.2],
        "low": [9.5, 19.5, 10.1], "close": [10.8, 20.2, 11.0],
        "volume": [1000, 2000, 1500],
        "dollar_volume": [10800.0, 40400.0, 16500.0],
        "n_sources": [2, 1, 3], "agree_flag": [True, False, True],
        "primary_source": ["src_a", "src_b", "src_a"],
        "flags": [None, "single_source", None],
    })


def corporate_actions():
    return pd.DataFrame({
        "security_id": ["S000001", "S000001"],
        "ex_date": D(["2024-01-10", "2024-01-10"]),
        "action": ["split", "cash_dividend"],
        "value": [2.0, 0.25], "source": ["src_a", "src_b"], "n_sources": [2, 1],
    })


def total_return_daily():
    return pd.DataFrame({
        "date": D(["2026-09-28", "2026-09-29"]),
        "security_id": ["S000001", "S000001"],
        "ret_1d": [None, 0.0185], "adj_factor": [1.0, 1.0],
    })


def universe_membership():
    return pd.DataFrame({
        "date": D(["2026-09-28", "2026-09-28"]),
        "security_id": ["S000001", "S000002"],
        "in_sp500": [True, False], "source_agree": [True, True],
    })


def delistings():
    return pd.DataFrame({
        "security_id": ["S000009"], "last_date": D(["2022-05-06"]),
        "reason": ["acquired"], "delisting_return": [float("nan")], "observed": [False],
    })


def fundamentals_pit():
    return pd.DataFrame({
        "security_id": ["S000001", "S000001"],
        "concept": ["Revenues", "Revenues"],
        "value": [1.0e6, 1.1e6],
        "period_end": D(["2026-03-31", "2026-06-30"]),
        "filed": D(["2026-05-01", "2026-08-01"]),
        "available_from": D(["2026-05-04", "2026-08-03"]),
    })


def macro_daily():
    return pd.DataFrame({
        "date": D(["2026-09-28", "2026-09-28"]),
        "series": ["RATE_A", "RATE_A"], "value": [4.1, 4.2],
        "vintage": D(["2026-09-29", "2026-09-30"]),
    })


ALL = {
    "security_master": security_master, "ticker_history": ticker_history,
    "prices_daily": prices_daily, "corporate_actions": corporate_actions,
    "total_return_daily": total_return_daily, "universe_membership": universe_membership,
    "delistings": delistings, "fundamentals_pit": fundamentals_pit, "macro_daily": macro_daily,
}
