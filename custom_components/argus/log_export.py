"""Logbook export (Logbook → Export): shop checks, price history per product, and price history in total.

All three read the stored data; nothing is fetched. The result is one CSV file: with one part chosen a
plain table, with several parts one table per part (a title line, then the header and the rows).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .const import RETAILERS
from .models import price_at, rows_to_csv, trusted

PARTS = ("checks", "history", "total", "reports")
DAY = 86400


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def select_products(store: dict[str, Any], f: dict[str, Any]) -> list[str]:
    """Product ids matching the product filters (all optional): products, category, priority."""
    out = []
    wanted = {str(x) for x in (f.get("products") or [])}
    for pid, p in store["products"].items():
        if wanted and pid not in wanted:
            continue
        if f.get("category") and p.get("category") != f["category"]:
            continue
        if f.get("priority") and int(p.get("priority") or 0) != int(float(f["priority"])):   # validated by the websocket
            continue
        out.append(pid)
    return out


def method(via: str | None, source: str | None) -> str:
    """How the price was read, in words: the shop's own site, or the user's browser."""
    if via in ("relay", "userscript") or source in ("relay", "userscript"):
        return "userscript (your browser)"
    if source == "panel" or source == "user":
        return "entered by hand"
    return "shop site (direct)"


def checks_rows(store: dict[str, Any], start: float, end: float, f: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per shop per check: when, product, shop, result, price, error, source."""
    wanted = {str(x) for x in (f.get("products") or [])}
    shops = set(f.get("shops") or [])
    status = f.get("status")                       # ok | failed | skipped
    rows = []
    for e in store.get("activity", []):
        if not start <= e.get("ts", 0) <= end:
            continue
        pid = e.get("product")
        if wanted and pid not in wanted:
            continue
        name = store["products"].get(pid, {}).get("name", "")
        if e.get("kind") == "userscript" and e.get("retailer") and e.get("price") is not None:
            # a price fetched by the browser (userscript / relay) is a check too
            rid = e["retailer"]
            st = "ok" if e.get("level") == "ok" else "failed"
            if (shops and rid not in shops) or (status and st != status):
                continue
            rows.append({"time": _stamp(e["ts"]), "product": pid, "name": name,
                         "shop": RETAILERS.get(rid, (rid,))[0], "result": st, "price": e["price"],
                         "error": "" if st == "ok" else e.get("message") or "", "via": e.get("source") or "",
                         "method": method(None, e.get("source")), "source": e.get("source") or ""})
            continue
        if e.get("kind") != "check":
            continue
        for rid, r in (e.get("results") or {}).items():
            if shops and rid not in shops:
                continue
            st = "ok" if r.get("ok") else "failed" if r.get("ok") is False else "skipped"
            if status and st != status:
                continue
            rows.append({"time": _stamp(e["ts"]), "product": pid, "name": name,
                         "shop": RETAILERS.get(rid, (rid,))[0], "result": st,
                         "price": r.get("price") if r.get("price") is not None else "", "error": r.get("error") or "",
                         "via": r.get("via") or "", "method": method(r.get("via"), e.get("source")) if st != "skipped" else "",
                         "source": e.get("source") or ""})
    rows.sort(key=lambda r: r["time"])
    return rows


def history_rows(store: dict[str, Any], pids: list[str], start: float, end: float, shops: set[str] | None = None) -> list[dict[str, Any]]:
    """Every recorded price per product and shop in the period."""
    rows = []
    for pid in pids:
        p = store["products"].get(pid, {})
        for rid, o in (store["offers"].get(pid) or {}).items():
            if shops and rid not in shops:
                continue
            for ts, price in o.get("history", []):
                if start <= ts <= end:
                    rows.append({"date": _stamp(ts), "product": pid, "name": p.get("name", ""), "category": p.get("category", ""),
                                 "shop": RETAILERS.get(rid, (rid,))[0], "price": price, "reference_price": p.get("ref_price") or ""})
    rows.sort(key=lambda r: (r["date"], r["product"]))
    return rows


def total_rows(store: dict[str, Any], pids: list[str], start: float, end: float) -> list[dict[str, Any]]:
    """Per day: how many of the chosen products have a price, and the sum of their lowest price that day
    (the lowest of all shops, last known price carried forward)."""
    series = {}
    for pid in pids:
        offers = trusted(store["offers"].get(pid) or {})
        series[pid] = [(ts, p) for o in offers.values() for ts, p in o.get("history", [])]
    first = min((ts for pts in series.values() for ts, _ in pts), default=None)
    if first is None:
        return []
    day = max(start, first)
    day = datetime.fromtimestamp(day).replace(hour=23, minute=59, second=59).timestamp()
    end = min(end, time.time())
    rows = []
    while day <= end + DAY - 1:
        total, n = 0.0, 0
        for pid in pids:
            offers = trusted(store["offers"].get(pid) or {})
            prices = [p for o in offers.values() if (p := price_at(o.get("history", []), day)) is not None]
            if prices:
                total += min(prices)
                n += 1
        rows.append({"date": _day(day), "products_with_price": n, "total_lowest_price": round(total, 2)})
        day += DAY
    return rows


COLUMNS = {
    "checks": ["time", "product", "name", "shop", "result", "price", "method", "error", "via", "source"],
    "history": ["date", "product", "name", "category", "shop", "price", "reference_price"],
    "total": ["date", "products_with_price", "total_lowest_price"],
}
TITLES = {"checks": "Shop checks", "history": "Price history per product", "total": "Price history in total"}


def build(store: dict[str, Any], opts: dict[str, Any]) -> tuple[str, dict[str, int]]:
    """(csv text, rows per part)."""
    parts = [p for p in PARTS if p in (opts.get("parts") or [])]
    start = float(opts.get("start") or 0)
    end = float(opts.get("end") or time.time())
    f = opts.get("filters") or {}
    pids = select_products(store, f)
    shops = set(f.get("shops") or []) or None
    tables = {}
    if "checks" in parts:
        tables["checks"] = checks_rows(store, start, end, f)      # only the product / shop / result filters apply here
    if "history" in parts:
        tables["history"] = history_rows(store, pids, start, end, shops)
    if "total" in parts:
        tables["total"] = total_rows(store, pids, start, end)
    reports = None
    if "reports" in parts:                         # 'Problem with this product' reports in the period (product filters apply)
        from . import report

        wanted = set(pids)
        reports = [r for r in store.get("reports", []) if start <= r["ts"] <= end and r["product"] in wanted]
    if len(tables) == 1 and reports is None:
        (key, rows), = tables.items()
        return rows_to_csv(rows, COLUMNS[key]), {key: len(rows)}
    chunks = [f"# {TITLES[k]}\n" + rows_to_csv(rows, COLUMNS[k]) for k, rows in tables.items()]
    counts = {k: len(v) for k, v in tables.items()}
    if reports is not None:
        chunks.append(report.to_csv(reports))
        counts["reports"] = len(reports)
    return "\n".join(chunks), counts
