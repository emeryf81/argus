"""Parser lab (Manage → Parser lab): fetch a shop page for a product (or paste its HTML), see what the parser
reads, and get a plain explanation of why there is no price, or a price that looks wrong, or why the page is
(not) judged to be the same product.
Admin only; a fetch goes through the same pacing and pauses as a normal check."""
from __future__ import annotations

import html as htmllib
import re
import time
from typing import Any
from urllib.parse import urlparse

from .const import RETAILERS
from .i18n import T
from .models import parse_price
from .parsers import (BLOCK_MARKERS, BUYBOX_IDS, _jsonld_blocks, _meta, _product_nodes, is_marketplace, parse_page,
                      product_match, retailer_from_url)
from .shops import domain_of, search_address

AMOUNT_RE = re.compile(r"(?:€|EUR)\s?(\d{1,4}(?:[.\s]\d{3})*[.,]\d{2})(?!\d)|(?<![\d.,])(\d{1,4}(?:[.\s]\d{3})*,\d{2})\s?(?:€|EUR)")
JS_HINT_RE = re.compile(r"enable javascript|javascript (?:is )?(?:required|disabled)|schakel javascript in|aktivieren sie javascript", re.I)
CONSENT_RE = re.compile(r"cookie|consent|toestemming|privacy settings|einwilligung", re.I)
SMALL_PAGE = 8000             # characters of visible text below which a product page is suspiciously empty


def links(coord: Any, rid: str, pid: str) -> dict[str, Any]:
    """The addresses the lab can test for this shop and product: the link you have and the shop's search page.
    'suggested' is the one filled in."""
    offer = coord.store["offers"].get(pid, {}).get(rid) or {}
    p = coord.store["products"].get(pid) or {}
    out = {"link": offer.get("url"),
           "search": search_address(rid, coord._search_words(p), p.get("ean")) if rid in RETAILERS and p else None}
    out["suggested"] = out["link"] or out["search"]
    return out


def visible_text(page: str) -> str:
    """The text you see (no scripts, styles or tags)."""
    s = re.sub(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>", " ", page)
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s))).strip()


def amounts(text: str, limit: int = 8) -> list[dict[str, Any]]:
    """Euro amounts in the text with a few words around them, the most frequent first."""
    seen: dict[float, dict[str, Any]] = {}
    for m in AMOUNT_RE.finditer(text):
        value = parse_price(m.group(1) or m.group(2))
        if value is None or value <= 0:
            continue
        hit = seen.setdefault(value, {"price": value, "count": 0, "context": text[max(0, m.start() - 50):m.end() + 30].strip()})
        hit["count"] += 1
    return sorted(seen.values(), key=lambda x: (-x["count"], x["price"]))[:limit]


def analyze(rid: str, page: str, parsed: Any, product: dict[str, Any] | None, *, status: int | None = None,
            error: str | None = None, url: str = "", final_url: str | None = None, known: float | None = None) -> dict[str, Any]:
    """What went right or wrong on this page, in plain words: a list of findings (level + text) and a verdict."""
    f: list[dict[str, str]] = []
    add = lambda level, text: f.append({"level": level, "text": text})  # noqa: E731
    if error:
        if status in (403, 429, 503) or "blocked" in error:
            add("bad", T("The shop refused the server ({error}). Try again later, or let your browser fetch it (userscript).", error=error))
        elif status == 404:
            add("bad", T("The page does not exist (any more): the link is out of date. Look up the product again or paste a new link."))
        else:
            add("bad", T("The page could not be fetched: {error}", error=error))
        return {"verdict": "error", "findings": f, "amounts": []}
    if not page:
        add("bad", T("The page is empty."))
        return {"verdict": "error", "findings": f, "amounts": []}
    text = visible_text(page)
    found = amounts(text)
    if parsed.blocked:
        marker = next((m for m in BLOCK_MARKERS if m.lower() in page[:200000].lower()), "?")
        add("bad", T("Bot protection: the shop shows a check (“{marker}”) instead of the product. Your browser usually gets through (userscript).", marker=marker))
        return {"verdict": "blocked", "findings": f, "amounts": found}
    host = (re.match(r"https?://([^/]+)", url or "") or [None, ""])[1].lower()
    dom = (domain_of(rid) or "").lower()
    if host and dom and not (host == dom or host.endswith("." + dom)):
        add("warn", T("The address is on {host}, not on {shop} ({domain}): pick the right shop or address.", host=host, shop=RETAILERS.get(rid, (rid,))[0], domain=dom))
    if final_url and url and final_url.split("?")[0].rstrip("/") != url.split("?")[0].rstrip("/"):
        add("warn", T("The shop sent the request on to {url}: the product may be gone, or the link is out of date.", url=final_url[:200]))
    if "/s?" in url or "search" in url.lower() or "zoek" in url.lower():
        add("info", T("This is a search page: the lab reads it like a product page. A check uses the product link found there."))
    if len(text) < SMALL_PAGE:
        js = bool(JS_HINT_RE.search(page)) or page.count("<script") > 20
        if CONSENT_RE.search(text) and parsed.price is None:
            add("warn", T("Very little text ({n} characters) and a cookie or consent message: the shop shows a consent page instead of the product.", n=len(text)))
        elif js:
            add("warn", T("Very little visible text ({n} characters): the page is built with JavaScript in the browser, so the server sees an empty shell. Your browser can render it (userscript, background tabs).", n=len(text)))
        else:
            add("info", T("Little visible text ({n} characters).", n=len(text)))
    if product:
        verdict, reason = product_match(product, parsed, url)
        if verdict == "ok":
            add("ok", T("This page is the same product: {reason}", reason=reason))
        elif verdict == "suspect":
            add("bad", T("This page does not look like the product “{name}”: {reason}", name=(product.get("name") or "")[:80], reason=reason))
    if parsed.gtins:
        add("info", T("Barcode(s) on the page: {gtins}", gtins=", ".join(parsed.gtins[:3])))
    else:
        add("info", T("No barcode (EAN/ISBN) found on the page: the product is judged by its title."))
    nodes = _product_nodes(page)
    ld_prices = []
    for n in nodes:
        from .parsers import _offer_prices

        ld_prices += _offer_prices(n.get("offers"))
    if nodes:
        add("info", T("Product data (JSON-LD): {n} product(s){prices}.", n=len(nodes),
                      prices=T(", price {prices}", prices=", ".join(f"€{p:.2f}" for p in ld_prices[:4])) if ld_prices else T(", without a price")))
    else:
        add("info", T("No product data (JSON-LD) on the page."))
    if (mp := _meta(page, "product:price:amount", "og:price:amount")):
        add("info", T("Price in the page's meta data: {price}", price=mp))
    if is_marketplace(rid) and parsed.price is None and not any(i in page for i in BUYBOX_IDS):
        add("info", T("No buy box on the page: the marketplace doesn't sell it new right now (not in stock)."))
    verdict = "ok"
    ref = (product or {}).get("ref_price")
    if parsed.price is not None:
        add("ok", T("Price read: €{price}", price=f"{parsed.price:.2f}"))
        if ref and parsed.price < 0.35 * ref:
            add("bad", T("€{price} is less than 35% of the reference price (€{ref}): probably an accessory, a part or another product.", price=f"{parsed.price:.2f}", ref=f"{ref:.2f}"))
            verdict = "suspect"
        elif ref and parsed.price > 2 * ref:
            add("warn", T("€{price} is more than twice the reference price (€{ref}): a marketplace seller, a bundle or another product?", price=f"{parsed.price:.2f}", ref=f"{ref:.2f}"))
            verdict = "suspect"
        if known and abs(parsed.price - known) / known > 0.4:
            add("warn", T("Differs a lot from the last price of this link (€{known}).", known=f"{known:.2f}"))
            verdict = "suspect"
    elif parsed.unavailable:
        add("ok", T("No price on purpose: the page says {reason}. That is a warning, not an error.",
                    reason=T("no longer sold (out of the range)") if parsed.reason == "discontinued" else T("sold out / not in stock")))
        verdict = "unavailable"
    else:
        verdict = "no_price"
        if found:
            add("bad", T("No price read, but the page has {n} amount(s) ({amounts}) in places the parser doesn't trust (no buy box, product data or price meta). If one of them is the price, this shop needs a new parser rule: send this result to the log or export it.",
                         n=len(found), amounts=", ".join(f"€{a['price']:.2f}" for a in found[:5])))
        else:
            add("bad", T("No price read and no euro amount anywhere in the visible text: the price is loaded later by JavaScript, or this isn't a product page."))
    return {"verdict": verdict, "findings": f, "amounts": found}


async def run(coord: Any, rid: str | None, pid: str | None, url: str, html: str = "") -> dict[str, Any]:
    """Fetch (or read pasted HTML), parse like a check does, and analyse the result."""
    rid = rid or (retailer_from_url(url) if url else None)
    if not rid or rid not in RETAILERS:
        raise ValueError(T("Pick a shop, or an address of a shop the integration knows."))
    status, error, final_url, ms = None, None, None, 0
    if html:
        page = html
    else:
        if not url.startswith(("https://", "http://")):
            raise ValueError(T("Give a full address (https://…)."))
        host, dom = (urlparse(url).hostname or "").lower().rstrip("."), (domain_of(rid) or "").lower()
        if not dom or not (host == dom or host.endswith("." + dom)):    # never another site or the local network
            raise ValueError(T("The address is not on {shop} ({domain}): pick the right shop or address.", shop=RETAILERS[rid][0], domain=dom or "?"))
        coord.manual_gate("site:" + coord._site(rid))
        t0 = time.time()
        status, page, error = await coord.fetcher.get_page(rid, url, force=True, note_block=False)
        ms, final_url = int((time.time() - t0) * 1000), coord.fetcher.final_url.get(rid)
    parsed = parse_page(rid, page or "")
    product = coord.store["products"].get(pid or "")
    offer = coord.store["offers"].get(pid or "", {}).get(rid) or {}
    known = offer.get("last_price") if offer.get("url") and (offer.get("url") or "").split("?")[0] == (url or "").split("?")[0] else None
    res = analyze(rid, page or "", parsed, product, status=status, error=error, url=url, final_url=final_url, known=known)
    return {"ts": time.time(), "retailer": rid, "shop": RETAILERS[rid][0], "product": pid, "url": url, "pasted": bool(html),
            "status": status, "error": error, "ms": ms, "final_url": final_url, "size": len(page or ""),
            "price": parsed.price, "list_price": parsed.list_price, "title": parsed.title, "image": parsed.image,
            "gtins": list(parsed.gtins), "mpn": parsed.mpn, "brand": parsed.brand, "category": parsed.category,
            "blocked": parsed.blocked, "unavailable": parsed.unavailable, "reason": parsed.reason,
            "ref_price": (product or {}).get("ref_price"), "known": known, **res, "head": (page or "")[:1500]}


def to_log(coord: Any, r: dict[str, Any]) -> None:
    """Put a lab result in the logbook (with every finding), for later analysis."""
    level = {"ok": "info", "unavailable": "info", "suspect": "warning"}.get(r.get("verdict"), "error")
    price = f"€{r['price']:.2f}" if r.get("price") is not None else T("no price")
    coord.log(level, "lab", T("Parser lab: {shop} → {result}", shop=r.get("shop") or r.get("retailer"), result=price),
              product=r.get("product"), retailer=r.get("retailer"), url=r.get("url"), source="user",
              details=[x.get("text", "") for x in r.get("findings", [])][:20])
