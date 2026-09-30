"""Fake transport and synthetic source payloads. Tickers and values are made up."""

import json

from ingest.http import Response, TransportError


class RoutingTransport:
    """Answers by URL substring. A route value may be a Response, an Exception or a
    callable(params) -> Response. Records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def send(self, method, url, *, params, headers, timeout, verify):
        self.calls.append(dict(url=url, params=params, headers=headers, verify=verify))
        for frag, item in self.routes.items():
            if frag in url:
                if callable(item) and not isinstance(item, Response):
                    item = item(params)
                if isinstance(item, Exception):
                    raise item
                return item
        raise TransportError("no route")


def resp(body, status=200):
    if isinstance(body, (dict, list)):
        body = json.dumps(body)
    if isinstance(body, str):
        body = body.encode()
    return Response(status, {"Content-Type": "text/plain"}, body)


def tickers(n, prefix="T"):
    return [f"{prefix}{i:03d}" for i in range(n)]


def symdir_nasdaq(n=5, created="0930202603:03"):
    rows = ["Symbol|Security Name|Market Category|Test Issue|Financial Status|"
            "Round Lot Size|ETF|NextShares"]
    for i, t in enumerate(tickers(n, "NQ")):
        rows.append(f"{t}|Synthetic {t} Common Stock|Q|{'Y' if i == 0 else 'N'}|N|100|"
                    f"{'Y' if i == 1 else 'N'}|N")
    rows.append(f"File Creation Time: {created}|||||||")
    return "\n".join(rows) + "\n"


def symdir_other(n=4, created="0930202603:03"):
    rows = ["ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|"
            "NASDAQ Symbol"]
    for t in tickers(n, "OT"):
        rows.append(f"{t}|Synthetic {t} Inc|N|{t}|N|100|N|{t}")
    rows.append(f"File Creation Time: {created}|||||||")
    return "\n".join(rows) + "\n"


def massive_grouped(n=100, close=10.0, drop_optional=False):
    results = []
    for i, t in enumerate(tickers(n, "M")):
        r = {"T": t, "o": close, "h": close + 1, "l": close - 1, "c": close + 0.5,
             "v": 1000 + i, "vw": close + 0.2, "t": 1790000000000, "n": 50}
        if drop_optional:
            r.pop("vw"), r.pop("n")
        if i == 0:
            r["otc"] = True
        results.append(r)
    return {"status": "OK", "adjusted": False, "queryCount": n, "resultsCount": n,
            "request_id": "synthetic", "results": results}


def fred_obs(dates, values, vintage="2026-09-30"):
    return {"observations": [
        {"realtime_start": vintage, "realtime_end": vintage, "date": d, "value": v}
        for d, v in zip(dates, values)]}


def membership_csv(snapshots):
    """snapshots: list of (date_str, [tickers])."""
    lines = ["date,tickers"] + [f'{d},"{",".join(ts)}"' for d, ts in snapshots]
    return "\n".join(lines) + "\n"
