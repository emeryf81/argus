"""Pure data logic (no Home Assistant imports) so it can be unit tested."""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date
from heapq import heappop, heappush
from itertools import groupby
from math import isfinite
from statistics import median
from typing import Any

from .const import CATEGORIES, DEFAULT_CATEGORY, MAX_HISTORY
from .i18n import LocalizedError, T


DAY = 86400


# --------------------------------------------------------------------- barcodes
def gtin_check(digits: str) -> bool:
    """GS1 check digit of an EAN-8 / UPC-12 / EAN-13 / GTIN-14."""
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalize_gtin(value: Any) -> str | None:
    """'978-90-234-1234-5' / ' 5901234123457 ' / ISBN-10 -> a valid barcode as digits (ISBN-10 becomes ISBN-13), else None."""
    s = re.sub(r"[\s-]", "", str(value or "")).upper()
    if re.fullmatch(r"\d{9}[\dX]", s):                                    # ISBN-10
        if sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s)) % 11:
            return None
        body = "978" + s[:9]
        return body + str((10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body)) % 10) % 10)
    return s if gtin_check(s) else None


def gtin_key(value: Any) -> str | None:
    """The comparable form of a barcode: valid digits without leading zeros (a UPC-12 equals its EAN-13 with a 0 in front)."""
    g = normalize_gtin(value)
    return g.lstrip("0") if g else None


def is_isbn(value: Any) -> bool:
    g = normalize_gtin(value)
    return bool(g) and len(g) == 13 and g[:3] in ("978", "979")


# ----------------------------------------------------------------------- products
def product_id(ean: Any = None, url: str | None = None) -> str:
    """A short stable id: from the barcode when the product has one (the same product added twice is the same product),
    else from the address it was added with."""
    key = gtin_key(ean)
    base = f"ean:{key}" if key else "url:" + re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).split("#")[0].rstrip("/")
    return "p" + hashlib.sha1(base.encode()).hexdigest()[:10]


def normalize_product_id(value: Any) -> str:
    return str(value or "").strip().lower()


def new_store() -> dict[str, Any]:
    return {"products": {}, "offers": {}, "snapshots": [], "events": [], "rejected": {}, "cooldowns": {}}


def parse_price(text: str | float | int | None) -> float | None:
    """Parse '1.234,56', '1,234.56', '39,99', '€ 39.99' ... into a float."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    s = re.sub(r"[^\d.,]", "", str(text))
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.rpartition(".")[2]) == 3):
        s = s.replace(".", "")
    try:
        value = float(s)
    except ValueError:
        return None
    return value if value > 0 else None


def record_price(offer: dict[str, Any], price: float | None, now: float | None = None,
                 error: str | None = None) -> bool:
    """Store an observation on an offer. Returns True if history changed."""
    now = now or time.time()
    offer["last_checked"] = now
    offer["error"] = error
    if price is None:
        offer["available"] = False
        return False
    offer["available"] = True
    offer["last_price"] = price
    hist: list[list[float]] = offer.setdefault("history", [])
    if hist:
        last_ts, last_price = hist[-1]
        same_day = int(last_ts // DAY) == int(now // DAY)
        if abs(last_price - price) < 0.005:
            return False
        if same_day:  # keep one point per day: overwrite with latest
            hist[-1] = [now, price]
            return True
    hist.append([now, price])
    if len(hist) > MAX_HISTORY:
        del hist[: len(hist) - MAX_HISTORY]
    return True


def price_at(history: list[list[float]], ts: float) -> float | None:
    """Last known price at or before ts (forward fill)."""
    result = None
    for t, p in history:
        if t <= ts:
            result = p
        else:
            break
    return result


def trusted(offers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Offers whose link is not flagged as pointing to the wrong product (manual links always count)."""
    return {rid: o for rid, o in offers.items() if o.get("link_status") not in ("suspect", "rejected") or o.get("manual_price")}


def offer_price(o: dict[str, Any]) -> float | None:
    """Price that counts for an offer: a manual price always wins over the automatic one."""
    if (m := o.get("manual_price")) and m.get("price"):
        return float(m["price"])
    return o.get("last_price") if o.get("available") else None


def best_offer(offers: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    """Cheapest currently available offer (suspect links excluded)."""
    live = [(rid, o) for rid, o in trusted(offers).items() if offer_price(o)]
    return min(live, key=lambda x: offer_price(x[1])) if live else None


def combined_history(offers: dict[str, dict[str, Any]]) -> list[list[float]]:
    """Cheapest-of-all-retailers series (forward filled) across all timestamps; suspect links excluded."""
    # Consume each observation once, including legacy histories beyond MAX_HISTORY.
    # Stable sorting preserves the last observation at duplicate timestamps.
    events = sorted(
        ((t, i, p) for i, o in enumerate(trusted(offers).values()) for t, p in o.get("history", [])),
        key=lambda event: event[0],
    )
    latest: dict[int, float] = {}
    prices: list[tuple[float, int]] = []
    out: list[list[float]] = []
    for ts, observations in groupby(events, key=lambda event: event[0]):
        for _, i, price in observations:
            latest[i] = price
            heappush(prices, (price, i))
        # Discard superseded prices lazily: each heap entry is removed at most once.
        while prices[0][0] != latest[prices[0][1]]:
            heappop(prices)
        out.append([ts, prices[0][0]])
    return out


def compute_status(
    product: dict[str, Any],
    offers: dict[str, dict[str, Any]],
    *,
    threshold: float,
    min_history_days: int,
    now: float | None = None,
) -> dict[str, Any]:
    """Derive price, lows and discount flags for one product."""
    now = now or time.time()
    best = best_offer(offers)
    series = combined_history(offers)
    status: dict[str, Any] = {
        "best_price": None, "best_retailer": None, "best_url": None,
        "all_time_low": None, "is_all_time_low": False,
        "discount_ref": None, "discount_avg": None,
        "high_discount": False, "history_days": 0, "offers_live": 0,
        "change_7d": None, "change_30d": None, "shop_spread": None, "highest_price": None,
        "target_price": product.get("target_price"), "target_hit": False,
        "offers_error": sum(1 for o in offers.values() if o.get("error")),
        "offers_suspect": sum(1 for o in offers.values() if o.get("link_status") == "suspect"),
        "deal_score": 0, "deal_label": None,
        "shops": [rid for rid, o in trusted(offers).items() if offer_price(o)],     # shops with a usable price now
    }
    status["offers_live"] = sum(1 for o in offers.values() if o.get("available"))
    if series:
        status["history_days"] = int((series[-1][0] - series[0][0]) // DAY)
        status["all_time_low"] = min(p for _, p in series)
    if not best:
        return status
    rid, offer = best
    price = offer_price(offer)
    status.update(best_price=price, best_retailer=rid, best_url=offer.get("url"))
    live_prices = [p for o in trusted(offers).values() if (p := offer_price(o))]
    if len(live_prices) >= 2:
        status["highest_price"] = max(live_prices)
        status["shop_spread"] = round((max(live_prices) - price) / max(live_prices) * 100, 1)
    if status["all_time_low"] is not None:
        # "record low" needs enough history to be meaningful
        status["is_all_time_low"] = (
            price <= status["all_time_low"] + 0.005
            and status["history_days"] >= min_history_days
            and len({p for _, p in series}) > 1
        )
    ref = product.get("ref_price")
    if ref:
        status["discount_ref"] = round((ref - price) / ref * 100, 1)
    recent = [p for t, p in series if now - t <= 90 * DAY]
    if len(recent) >= 3:
        avg = median(recent)
        status["discount_avg"] = round((avg - price) / avg * 100, 1)
    for key, days in (("change_7d", 7), ("change_30d", 30)):
        old = price_at(series, now - days * DAY)
        if old:
            status[key] = round((price - old) / old * 100, 1)
    target = product.get("target_price")
    status["target_hit"] = bool(target) and price <= float(target)
    refd = status["discount_ref"] if status["discount_ref"] is not None else status["discount_avg"]
    status["high_discount"] = refd is not None and refd >= threshold
    status["deal_score"] = deal_score(status)
    status["deal_label"] = "top" if status["deal_score"] >= 70 else "good" if status["deal_score"] >= 45 else None
    return status


def deal_score(st: dict[str, Any]) -> int:
    """0-100: how good is the current price? Weighs the discount against your reference price, against the 90-day
    median, the distance to the all-time low, how much cheaper the best shop is than the dearest one, and a reached
    target price. Without a reference price the 90-day median counts for more."""
    price = st.get("best_price")
    if not price:
        return 0
    score = 0.0
    has_ref = st.get("discount_ref") is not None
    if has_ref:
        score += min(max(st["discount_ref"], 0), 50) / 50 * 40
    atl = st.get("all_time_low")
    if atl and st.get("history_days", 0) >= 1:
        gap = (price - atl) / atl
        score += 25 if gap <= 0.005 else max(0.0, 1 - gap / 0.2) * 20
    if st.get("discount_avg") is not None:
        score += min(max(st["discount_avg"], 0), 25) / 25 * (20 if has_ref else 35)
    if st.get("shop_spread") is not None:
        score += min(max(st["shop_spread"], 0), 25) / 25 * 10
    if st.get("target_hit"):
        score += 10
    return int(round(min(score, 100)))


def clean_history(offer: dict[str, Any], ref: float | None) -> int:
    """Drop impossible price points (< 20 % or > 4× the reference price), e.g. an accessory price read by mistake.
    Returns the number of removed points; fixes last_price when the latest point was removed."""
    if not ref:
        return 0
    hist = offer.get("history", [])
    manual = (offer.get("manual_price") or {}).get("price")
    keep = [h for h in hist if ref * 0.2 <= h[1] <= ref * 4 or (manual and abs(h[1] - manual) < 0.005)]
    removed = len(hist) - len(keep)
    if removed:
        offer["history"] = keep
        if offer.get("last_price") is not None and not ref * 0.2 <= offer["last_price"] <= ref * 4:
            offer["last_price"] = keep[-1][1] if keep else None
            offer["available"] = bool(keep) and offer.get("available", False)
    return removed


def agreeing_group(prices: list[float]) -> list[float]:
    """The lowest group of at least two prices that agree (each within ±50 % of the group's lowest price)."""
    ps = sorted(p for p in prices if p and p > 0)
    for i, low in enumerate(ps):
        group = [p for p in ps[i:] if p <= low * 1.5]
        if len(group) >= 2:
            return group
    return []


def is_suspicious_price(price: float, product: dict[str, Any], offer: dict[str, Any],
                        others: list[float] | None = None) -> str | None:
    """Catch parse errors (accessory/marketplace/multi-pack prices, cents read without the comma) before
    they pollute history. The other shops' prices for the same product are the yardstick; your reference price
    helps when there are none."""
    ap = offer.get("approved")
    if ap and abs(price - ap) <= ap * 0.25:
        return None              # you approved a price like this for this link: the shop really asks it
    ref = product.get("ref_price")
    group = agreeing_group(others or [])
    if ref and group and not 0.25 <= ref / median(group) <= 4:
        ref = None               # shops that agree contradict the reference price: don't trust it
    if not ref and others:
        mid = median(others)
        if price > mid * 4:      # far above the others: e.g. cents read without the comma
            return T("suspicious price €{price} (far from €{usual}) ignored", price=f"{price:.2f}", usual=f"{mid:.2f}")
        # far below needs two other shops that agree with each other (an accessory, not one odd quote)
        group = agreeing_group(others)
        if group and price < median(group) * 0.25:
            return T("suspicious price €{price} (far from €{usual}) ignored", price=f"{price:.2f}", usual=f"{median(group):.2f}")
    if ref and price < ref * 0.2:
        return T("suspicious price €{price} (under 20% of the reference price) ignored", price=f"{price:.2f}")
    if ref and price > ref * 4:
        return T("suspicious price €{price} (over 4× the reference price) ignored", price=f"{price:.2f}")
    prices = [p for _, p in offer.get("history", [])]
    if not ref and len(prices) >= 3:
        mid = median(prices)
        if price < mid * 0.25 or price > mid * 4:
            return T("suspicious price €{price} (far from €{usual}) ignored", price=f"{price:.2f}", usual=f"{mid:.2f}")
    return None


# --------------------------------------------------------------------- events/log
def add_event(store: dict[str, Any], kind: str, payload: dict[str, Any], now: float | None = None,
              keep: int = 200) -> None:
    events = store.setdefault("events", [])
    events.append({"ts": now or time.time(), "kind": kind, **payload})
    del events[: max(0, len(events) - keep)]


def parse_times(raw: str) -> list[str]:
    """'7:30, 19.30 en 23u05' -> ['07:30', '19:30', '23:05'] (sorted, unique, valid only)."""
    out = {f"{int(h):02d}:{mm}" for h, mm in re.findall(r"(\d{1,2})[:.hu](\d{2})", raw or "") if int(h) < 24 and int(mm) < 60}
    return sorted(out)


# ------------------------------------------------------------------ activity log
ACTIVITY_MAX = 6000
ACTIVITY_KINDS = {
    "check": "Shop check", "price": "Price change", "fetch": "Shop connection", "discover": "Link search", "link": "Link check",
    "userscript": "Userscript (Tampermonkey)", "import": "Import", "job": "Job", "notify": "Notification",
    "meta": "Product data", "user": "Your action", "settings": "Settings", "shop": "Shop status", "report": "Problem report",
    "lab": "Parser lab",
}


def add_activity(store: dict[str, Any], level: str, kind: str, message: str, *, now: float | None = None,
                 **fields: Any) -> dict[str, Any]:
    """Append to the activity log. An identical message for the same product/shop right after the previous
    one is collapsed (count + time updated) so repeated failures don't flood the log."""
    log = store.setdefault("activity", [])
    now = now or time.time()
    fields = {k: v for k, v in fields.items() if v is not None}
    for prev in reversed(log[-20:]):
        if prev.get("product") == fields.get("product") and prev.get("retailer") == fields.get("retailer") \
                and prev.get("kind") == kind:
            if prev["message"] == message and prev["level"] == level:
                prev["count"] = prev.get("count", 1) + 1
                prev["ts"] = now
                prev.update(fields)             # keep the latest details (e.g. per-shop results)
                return prev
            break
    entry = {"id": f"{int(now * 1000):x}{len(log) % 1000:03d}", "ts": now, "level": level, "kind": kind,
             "message": message[:500], **fields}
    log.append(entry)
    if len(log) > ACTIVITY_MAX:
        del log[: len(log) - ACTIVITY_MAX]
    return entry


def query_activity(store: dict[str, Any], *, level: str = "", kind: str = "", retailer: str = "", source: str = "",
                   product: str = "", q: str = "", status: str = "", before: float | None = None,
                   limit: int = 100) -> dict[str, Any]:
    """Filter the log (newest first). level: '' | 'problems' (error+warning) | 'events' (info+ok) | exact."""
    log = store.get("activity", [])
    q = q.strip().lower()
    pid = normalize_product_id(product)

    def ok(e: dict[str, Any]) -> bool:
        """Return whether an activity entry matches the requested filters and time boundary."""
        if level == "problems" and e["level"] not in ("error", "warning"):
            return False
        if level == "events" and e["level"] not in ("info", "ok"):
            return False
        if level not in ("", "problems", "events") and e["level"] != level:
            return False
        if kind and e["kind"] != kind or source and e.get("source") != source:
            return False
        res = e.get("results") or {}
        if retailer and e.get("retailer") != retailer and retailer not in res:
            return False
        if status == "suspect":         # a price that was held back as suspicious (can be approved)
            txt = " ".join(str((r or {}).get("error") or "") for r in res.values()) + " " + e["message"]
            if "suspicious price" not in txt:
                return False
        if status in ("ok", "fail"):
            if retailer and retailer in res:
                good = res[retailer].get("ok")
            else:
                good = e["level"] in ("ok", "info") if not res else all(r.get("ok") is not False for r in res.values())
            if (status == "ok") != bool(good):
                return False
        if pid and e.get("product") != pid:
            return False
        if q and q not in (e["message"] + " " + (e.get("url") or "") + " " + (e.get("product") or "")).lower():
            return False
        return before is None or e["ts"] < before

    matched = [e for e in reversed(log) if ok(e)]
    facets: dict[str, dict[str, int]] = {"kind": {}, "retailer": {}, "source": {}, "level": {}}
    for e in log:
        for f in facets:
            if e.get(f):
                facets[f][e[f]] = facets[f].get(e[f], 0) + 1
        for rid in (e.get("results") or {}):
            if rid != e.get("retailer"):
                facets["retailer"][rid] = facets["retailer"].get(rid, 0) + 1
    return {"entries": matched[:limit], "total": len(matched), "more": len(matched) > limit, "facets": facets,
            "kinds": ACTIVITY_KINDS}


def today_iso(now: float | None = None) -> str:
    return date.fromtimestamp(now or time.time()).isoformat()


# --------------------------------------------------------------------------- basket
def basket_summary(store: dict[str, Any], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Everything you track together: what it costs now at the cheapest shops, against your reference prices."""
    cost = ref = 0.0
    priced = 0
    by_category: dict[str, dict[str, Any]] = {}
    for pid, p in store["products"].items():
        cat = by_category.setdefault(p.get("category") or DEFAULT_CATEGORY, {"products": 0, "cost": 0.0})
        cat["products"] += 1
        price = statuses.get(pid, {}).get("best_price")
        if price:
            priced += 1
            cost += price
            ref += p.get("ref_price") or price
            cat["cost"] = round(cat["cost"] + price, 2)
    return {"products": len(store["products"]), "priced": priced, "cost": round(cost, 2), "ref": round(ref, 2),
            "saving": round(ref - cost, 2), "by_category": by_category}


def basket_series(store: dict[str, Any], now: float | None = None, points: int = 120) -> list[dict[str, float]]:
    """The cost of everything you track over time: per moment the sum of each product's cheapest price then."""
    now = now or time.time()
    hists = [h for pid, offers in store["offers"].items() if pid in store["products"] and (h := combined_history(offers))]
    if not hists:
        return []
    first = min(h[0][0] for h in hists)
    span = max(now - first, DAY)
    out = []
    for i in range(points + 1):
        t = first + span * i / points
        prices = [p for h in hists if (p := price_at(h, t)) is not None]
        if prices:
            out.append({"t": round(t), "cost": round(sum(prices), 2), "n": len(prices)})
    return out


# ----------------------------------------------------------------------- summary/export
PRODUCT_COLUMNS = ["URL", "Name", "Category", "EAN", "Brand", "Model", "Reference Price", "Target Price", "Priority", "Notes"]


def product_rows(store: dict[str, Any], statuses: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows in the same layout `csv_import` understands, so export -> import round-trips."""
    rows = []
    for pid, p in store["products"].items():
        rows.append({"URL": p.get("source_url") or "", "Name": p.get("name", ""), "Category": p.get("category", ""),
                     "EAN": p.get("ean") or "", "Brand": p.get("brand") or "", "Model": p.get("mpn") or "",
                     "Reference Price": p.get("ref_price") or "", "Target Price": p.get("target_price") or "",
                     "Priority": p.get("priority") or "", "Notes": p.get("notes") or ""})
    return sorted(rows, key=lambda r: r["Name"].lower())


def rows_to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    import csv
    import io

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    w.writeheader()

    def safe(v: Any) -> Any:
        # Spreadsheet formula injection guard. A value that already starts with an apostrophe gets one too, so
        # the importer can always remove exactly one leading apostrophe before =, +, -, @ or ' and get the
        # original text back.
        return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "'") else v

    w.writerows({k: safe(v) for k, v in r.items()} for r in rows)
    return out.getvalue()


def validate_backup(data: Any) -> dict[str, Any]:
    """Sanity-check an imported backup and return a clean store (never trusts the file blindly)."""
    if not isinstance(data, dict) or not isinstance(data.get("products"), dict):
        raise LocalizedError("Not an ARGUS backup (field 'products' is missing).")
    clean = new_store()
    for key in clean:
        if key in data:
            if type(data[key]) is not type(clean[key]):
                raise LocalizedError("Field {field} in the backup has the wrong type.", field=key)
            clean[key] = data[key]
    for pid, p in clean["products"].items():
        if not re.fullmatch(r"p[0-9a-f]{10}", str(pid)) or not isinstance(p, dict):
            raise LocalizedError("Invalid product {id} in the backup.", id=pid)
        for k in ("ref_price", "target_price"):
            if k in p and p[k] is not None and not isinstance(p[k], (int, float)):
                raise LocalizedError("Product {id}: {field} is not a number.", id=pid, field=k)
        if p.get("category") not in (None, *CATEGORIES):
            raise LocalizedError("Product {id}: unknown category.", id=pid)
    for pid, offers in clean["offers"].items():
        if pid not in clean["products"] or not isinstance(offers, dict):
            raise LocalizedError("Offers for unknown product {id}.", id=pid)
        for rid, o in offers.items():
            url = o.get("url", "") if isinstance(o, dict) else None
            if url is None or (url and not str(url).startswith(("https://", "http://"))):
                raise LocalizedError("Product {id}/{shop}: invalid URL.", id=pid, shop=rid)
            hist = o.get("history", [])
            if not isinstance(hist, list) or len(hist) > MAX_HISTORY or any(
                not isinstance(h, list) or len(h) != 2
                or not all(type(x) in (int, float) and (not isinstance(x, float) or isfinite(x)) for x in h)
                for h in hist
            ) or any(a[0] > b[0] for a, b in zip(hist, hist[1:])):
                raise LocalizedError("Product {id}/{shop}: invalid price history.", id=pid, shop=rid)
    return clean
