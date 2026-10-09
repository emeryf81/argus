"""'Problem with this product': a snapshot of everything the integration knows about one product (links, prices,
errors, recent log), with what the user says is wrong. Written to the logbook and/or exported as CSV."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .const import RETAILERS
from .models import rows_to_csv

PROBLEMS = ("link", "shop", "price", "data", "image", "status", "other")
REPORTS_MAX = 200


def _stamp(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""


def build(store: dict[str, Any], pid: str, status: dict[str, Any], problems: list[str], shops: list[str],
          comment: str) -> dict[str, Any]:
    """The report itself (stored as is; the CSV is made from it)."""
    p = store["products"].get(pid, {})
    offers = {}
    for rid, o in (store["offers"].get(pid) or {}).items():
        offers[rid] = {
            "shop": RETAILERS.get(rid, (rid,))[0], "url": o.get("url") or "", "manual_url": bool(o.get("manual_url")),
            "link_status": o.get("link_status") or "", "link_reason": o.get("link_reason") or "",
            "title": (o.get("title") or "")[:200], "price": o.get("last_price") if o.get("available") else None,
            "manual_price": (o.get("manual_price") or {}).get("price"), "auto_price": o.get("auto_price"),
            "available": o.get("available"), "error": o.get("error") or "",
            "last_checked": o.get("last_checked"), "last_ok": o.get("last_ok"),
            "recent_prices": [[round(ts), pr] for ts, pr in (o.get("history") or [])[-10:]],
        }
    log = [{"ts": e["ts"], "level": e["level"], "kind": e["kind"], "shop": e.get("retailer") or "",
            "message": e["message"], "url": e.get("url") or ""}
           for e in store.get("activity", []) if e.get("product") == pid][-30:]
    return {
        "id": f"r{int(time.time() * 1000):x}", "ts": time.time(), "product": pid,
        "problems": [x for x in problems if x in PROBLEMS], "shops": [r for r in shops if r in offers or r in RETAILERS],
        "comment": comment.strip()[:2000],
        "item": {k: p.get(k) for k in ("name", "brand", "category", "ean", "mpn", "ref_price", "target_price", "image", "source_url")},
        "status": {k: status.get(k) for k in ("best_price", "best_retailer", "best_url", "all_time_low", "discount_ref",
                                              "deal_score", "offers_live", "offers_error", "offers_suspect")},
        "offers": offers, "log": log,
    }


SHOP_COLUMNS = ["report_time", "product", "name", "problems", "comment", "shop", "flagged", "url", "manual_link",
                "link_status", "link_reason", "price", "manual_price", "auto_price", "available", "error",
                "last_checked", "last_ok", "recent_prices", "best_price", "best_shop", "reference_price"]
LOG_COLUMNS = ["report_time", "product", "time", "level", "kind", "shop", "message", "url"]


def shop_rows(r: dict[str, Any]) -> list[dict[str, Any]]:
    base = {"report_time": _stamp(r["ts"]), "product": r["product"], "name": r["item"].get("name") or "",
            "problems": " ".join(r["problems"]), "comment": r["comment"],
            "best_price": r["status"].get("best_price") or "", "best_shop": r["status"].get("best_retailer") or "",
            "reference_price": r["item"].get("ref_price") or ""}
    rows = []
    for rid, o in r["offers"].items():
        rows.append({**base, "shop": o["shop"], "flagged": "yes" if rid in r["shops"] else "", "url": o["url"],
                     "manual_link": "yes" if o["manual_url"] else "", "link_status": o["link_status"],
                     "link_reason": o["link_reason"], "price": o["price"] if o["price"] is not None else "",
                     "manual_price": o["manual_price"] or "", "auto_price": o["auto_price"] or "",
                     "available": "" if o["available"] is None else ("yes" if o["available"] else "no"),
                     "error": o["error"], "last_checked": _stamp(o["last_checked"]), "last_ok": _stamp(o["last_ok"]),
                     "recent_prices": " ".join(f"{_stamp(ts)[:10]}={pr}" for ts, pr in o["recent_prices"])})
    return rows or [base]


def to_csv(reports: list[dict[str, Any]]) -> str:
    """Two tables: per report and shop what is known, then the recent log of each reported product."""
    shops = [row for r in reports for row in shop_rows(r)]
    logs = [{"report_time": _stamp(r["ts"]), "product": r["product"], "time": _stamp(e["ts"]), "level": e["level"],
             "kind": e["kind"], "shop": e["shop"], "message": e["message"], "url": e["url"]} for r in reports for e in r["log"]]
    return "# Problem reports: shops\n" + rows_to_csv(shops, SHOP_COLUMNS) + "\n# Problem reports: recent log\n" + rows_to_csv(logs, LOG_COLUMNS)


def save(store: dict[str, Any], report: dict[str, Any]) -> None:
    reports = store.setdefault("reports", [])
    reports.append(report)
    del reports[: max(0, len(reports) - REPORTS_MAX)]
