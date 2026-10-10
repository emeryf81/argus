"""Finders: web search engines and price-comparison sites used to find a product's page at a shop.

A finder is a website listed in the shop settings file (so it falls under the same terms and the same legal gate as a
shop). Two kinds:

  websearch   a search engine; ARGUS searches "<brand> <name> <shop>" and takes the first result on the shop's domain
  aggregator  a comparison / shopping site (its sponsored product ads included); one search per product returns links
              to many shops at once

Whatever a finder returns is only a *suggestion*: it is a link to the shop, and the shop's own product page is still
fetched and verified (barcode, model number, title, accessory words) before it is linked. The price next to a link at a
comparison site (and the comparison service that shows it: Shoparize, Producthero, Channable…) is kept as well; it is
used when the shop's own page can't be read, marked with that service's letter in a circle.
"""
from __future__ import annotations

import base64
import binascii
import html as htmllib
import re
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

from .parsers import ASSET_RE, accessory_word, is_search_url, normalize_url, slug_title, title_score

KINDS = ("websearch", "aggregator")
URL_RE = re.compile(r"https?(?::|%3[Aa])(?://|%2[Ff]%2[Ff])[^\s\"'<>\\]+")
HREF_RE = re.compile(r"<a\b[^>]*?\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _flatten(raw: str) -> str:
    """Page text with the escapes web pages use inside scripts and attributes undone."""
    text = raw.replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u002F", "/").replace("\\u003a", ":")
    return htmllib.unescape(text)


def _urls_in(value: str) -> list[str]:
    """Every http(s) address inside a value, also when it is percent-encoded or hidden in a redirect parameter
    (url=, adurl=, uddg=, u=, ued=…) or in Bing's base64 click addresses (u=a1aHR0…)."""
    out: list[str] = []

    def walk(text: str, depth: int) -> None:
        if depth > 3:
            return
        for m in URL_RE.finditer(text):
            raw = m.group(0)
            if m.start() > 0 and text[m.start() - 1] == "=":          # a value inside a query string ends at the next &
                raw = raw.split("&", 1)[0]
            url = unquote(raw) if "%3" in raw[:12].lower() else raw
            if url not in out:
                out.append(url)
            for _k, v in parse_qsl(urlparse(url).query, keep_blank_values=False):
                if v.startswith("a1") and len(v) > 12:           # Bing: "a1" + base64url of the target
                    try:
                        walk(base64.urlsafe_b64decode(v[2:] + "=" * (-len(v[2:]) % 4)).decode("utf-8", "ignore"), depth + 1)
                    except (binascii.Error, ValueError):
                        pass
                elif "http" in v.lower():
                    walk(unquote(v), depth + 1)

    walk(value, 0)
    return out


def _host_ok(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


# Comparison Shopping Services (CSS) and comparison sites whose name appears next to an offer ("By Shoparize",
# "Door Producthero"…): the price is then shown with that service's circled letter, so you see where it came from.
CSS_SERVICES: dict[str, tuple[str, str]] = {
    "shoparize": ("Shoparize", "s"), "producthero": ("Producthero", "p"), "channable": ("Channable", "c"),
    "kelkoo": ("Kelkoo", "k"), "idealo": ("idealo", "i"), "pricerunner": ("PriceRunner", "r"), "beslist": ("Beslist", "b"),
    "tweakers": ("Tweakers", "t"), "google": ("Google Shopping", "g"), "bing": ("Bing Shopping", "m"),
    "smarter ecommerce": ("smec", "e"), "adtraction": ("Adtraction", "a"), "vergelijk": ("Vergelijk", "v"),
}
CSS_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(CSS_SERVICES, key=len, reverse=True)) + r")\b", re.I)
PRICE_RE = re.compile(r"(?:€|EUR)\s*(\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d)"
                      r"|(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})*[.,]\d{2}|\d+[.,]\d{2})\s*(?:€|EUR)", re.I)
LDJSON_RE = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
# hosts that are never a shop (search engines, ads, social networks, the comparison services themselves, CDNs)
NOT_SHOPS = re.compile(r"(?:^|\.)(?:google|googleadservices|googlesyndication|doubleclick|gstatic|googleusercontent|youtube|"
                       r"bing|microsoft|msn|duckduckgo|yahoo|facebook|instagram|twitter|x|tiktok|pinterest|linkedin|"
                       r"wikipedia|wikimedia|reddit|cloudflare|jsdelivr|schema|w3|apple-mapkit|"
                       + "|".join(re.escape(k.replace(" ", "")) for k in CSS_SERVICES) + r")\.[a-z.]+$", re.I)
WINDOW_BEFORE, WINDOW_AFTER = 250, 450        # characters of page text around a link that belong to its offer


def css_of(text: str) -> str | None:
    """The comparison service named in an offer's text ('shoparize', …), or None."""
    m = CSS_RE.search(text or "")
    return m.group(1).lower() if m else None


def _first_price(text: str, last: bool = False) -> float | None:
    """The first (or last) price in a piece of text."""
    from .models import parse_price

    found = [v for m in PRICE_RE.finditer(text) if (v := parse_price(m.group(1) or m.group(2))) and v <= 100_000]
    return (found[-1] if last else found[0]) if found else None


def _ld_offers(page: str) -> list[dict[str, Any]]:
    """Offers in the page's structured data (JSON-LD): url, price and seller name."""
    import json

    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Offer" in kinds and node.get("url"):
                from .models import parse_price

                seller = node.get("seller")
                out.append({"url": str(node["url"]), "price": parse_price(node.get("price") or node.get("lowPrice")),
                            "seller": seller.get("name") if isinstance(seller, dict) else seller})
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)

    for m in LDJSON_RE.finditer(page):
        try:
            walk(json.loads(m.group(1)))
        except ValueError:
            continue
    return out


def offers(page: str, domains: dict[str, str], product: dict[str, Any] | None = None,
           skip: set[str] | frozenset[str] = frozenset(), url_key: Any = None, own_domain: str = "",
           ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Offers in a finder's result page.

    Returns ({shop id: [{"url", "title", "score", "price", "css"}]} best first, [offers at shops that are not in your
    list yet: {"domain", "url", "title", "score", "price", "css", "seller"}]).
    Every address on a shop's domain counts, organic or sponsored (ads hide the shop's address in a redirect
    parameter). Search pages, home pages and pictures are dropped, and so is a link whose text or address names an
    accessory; the rest is ranked by how well its text covers the product's name. The price and the comparison service
    next to a link come from the text around it (or from the page's structured data)."""
    raw_page = page
    text = _flatten(page)
    plain_parts: list[str] = []
    hits: list[tuple[str, str, int]] = []          # (address, link text, position in the plain text)
    spans: list[tuple[int, int]] = []              # where every link's text sits in the plain text
    last = 0
    plain_len = 0
    for m in HREF_RE.finditer(text):
        before = " " + " ".join(TAG_RE.sub(" ", text[last:m.start()]).split()) + " "
        plain_parts.append(before)
        plain_len += len(before)
        label = " ".join(htmllib.unescape(TAG_RE.sub(" ", m.group(3))).split())[:200]
        for u in _urls_in(m.group(2)):
            hits.append((u, label, plain_len))
        spans.append((plain_len, plain_len + len(label)))
        plain_parts.append(label)
        plain_len += len(label)
        last = m.end()
    plain_parts.append(" " + " ".join(TAG_RE.sub(" ", text[last:]).split()))
    plain = "".join(plain_parts)
    seen_urls = {h[0] for h in hits}
    for u in _urls_in(text):                      # addresses in scripts / data attributes (no link text)
        if u not in seen_urls:
            hits.append((u, "", -1))
            seen_urls.add(u)
    ld = {o["url"]: o for o in _ld_offers(raw_page)}
    name, brand = (product or {}).get("name"), (product or {}).get("brand")
    found: dict[str, dict[str, dict[str, Any]]] = {}
    others: dict[str, dict[str, Any]] = {}
    for pos, (raw, label, at) in enumerate(hits):
        try:
            url = normalize_url(raw)
        except ValueError:
            continue
        p = urlparse(url)
        host = (p.hostname or "").lower()
        path = p.path
        if len(path.strip("/")) < 3 or is_search_url(url) or ASSET_RE.search(path):
            continue
        words = f"{label} {slug_title(url)}".strip()
        if accessory_word(words, name):
            continue
        score = title_score(name, brand, words)[0] if name and words else 0.0
        ldo = ld.get(raw) or ld.get(url) or {}
        after = before = ""
        if at >= 0:                               # the offer's text: up to the next link, else back to the previous one
            i = next(k for k, sp in enumerate(spans) if sp[0] == at)
            end = spans[i][1]
            after = plain[end:min(end + WINDOW_AFTER, spans[i + 1][0] if i + 1 < len(spans) else len(plain))]
            before = plain[max(at - WINDOW_BEFORE, spans[i - 1][1] if i else 0):at]
        price = ldo.get("price") or _first_price(after) or _first_price(before, last=True)
        css = css_of(after) or css_of(before) or css_of(ldo.get("seller") or "")
        item = {"url": url, "title": label, "score": score, "pos": pos, "price": price, "css": css}
        rid = next((r for r, d in domains.items() if _host_ok(url, d)), None)
        if rid:
            key = url_key(rid, url) if url_key else path.lower()
            if key in skip:
                continue
            cur = found.setdefault(rid, {})
            if key not in cur or score > cur[key]["score"]:
                cur[key] = item
        elif host and not NOT_SHOPS.search(host) and not (own_domain and _host_ok(url, own_domain)) and price:
            dom = host.removeprefix("www.")
            if dom not in others or score > others[dom]["score"]:
                others[dom] = {**item, "domain": dom, "seller": ldo.get("seller")}
    by_shop = {rid: sorted(c.values(), key=lambda x: (-round(x["score"], 1), x["pos"])) for rid, c in found.items()}
    return by_shop, sorted(others.values(), key=lambda x: (-x["score"], x["pos"]))


def extract(page: str, domains: dict[str, str], product: dict[str, Any] | None = None,
            skip: set[str] | frozenset[str] = frozenset(), url_key: Any = None) -> dict[str, list[dict[str, Any]]]:
    """Links to your shops in a finder's result page: {shop id: [{"url", "title", "score", "price", "css"}]}, best first."""
    return offers(page, domains, product, skip, url_key)[0]
