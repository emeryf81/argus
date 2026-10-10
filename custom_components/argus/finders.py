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
ALT_RE = re.compile(r"<img\b[^>]*?\b(?:alt|title)\s*=\s*([\"'])(.*?)\1[^>]*>", re.I | re.S)   # shop logos carry the shop's name
CTA_RE = re.compile(r"^(?:|naar (?:de )?winkel|naar shop|bekijk|bekijken|bekijk aanbieding|ga naar.*|bezoek.*|koop.*|kopen|shop|"
                    r"to (?:the )?shop|visit.*|buy.*|vers la boutique|voir l'offre|zum shop|aanbieding|deal|€.*|\d.*)$", re.I)


def _text(html: str) -> str:
    """The visible text of a piece of HTML (pictures count with their alt text: shop logos)."""
    return " ".join(htmllib.unescape(TAG_RE.sub(" ", ALT_RE.sub(lambda m: f" {m.group(2)} ", html))).split())


def _named(text: str, names: list[tuple[str, str]], last: bool = False) -> str | None:
    """The shop (id) whose name appears in a text: the first one, or the last one before a link."""
    low = f" {text.lower()} "
    best: tuple[int, str] | None = None
    for alias, rid in names:
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", low):
            if best is None or (m.start() > best[0] if last else m.start() < best[0]):
                best = (m.start(), rid)
    return best[1] if best else None


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
    "kelkoo": ("Kelkoo", "k"), "kieskeurig": ("Kieskeurig", "q"), "idealo": ("idealo", "i"), "pricerunner": ("PriceRunner", "r"), "beslist": ("Beslist", "b"),
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


PRIVATE_SUFFIX = re.compile(r"(?:^|\.)(?:localhost|local|lan|internal|intranet|home|corp|arpa|test|invalid|example|onion)$", re.I)


def public_host(host: str) -> bool:
    """A name that can only be a shop on the public internet: no IP address, no single word, no local or reserved
    suffix. (Shops found through a comparison site are fetched by the server, so a link to the local network that a
    page might carry must never become a shop.)"""
    import ipaddress

    host = (host or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False
    except ValueError:
        pass
    labels = host.split(".")
    return (len(labels) >= 2 and re.fullmatch(r"[a-z]{2,24}", labels[-1]) is not None and not PRIVATE_SUFFIX.search(host)
            and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels))


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
           names: list[tuple[str, str]] | None = None) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Offers in a finder's result page.

    Returns ({shop id: [{"url", "title", "score", "price", "css"}]} best first, [offers at shops that are not in your
    list yet: {"domain", "url", "title", "score", "price", "css", "seller"}]).
    Every address on a shop's domain counts, organic or sponsored (ads hide the shop's address in a redirect
    parameter). Search pages, home pages and pictures are dropped, and so is a link whose text or address names an
    accessory; the rest is ranked by how well its text covers the product's name. The price and the comparison service
    next to a link come from the text around it (or from the page's structured data).

    Comparison sites such as Tweakers, Kieskeurig and Beslist send you to the shop through a link on their own site
    (a click-out): there the shop is recognised by its name or logo next to the price (names: [(name, shop id)]); such
    an offer has a price but no address of the shop ("url": None)."""
    raw_page = page
    text = _flatten(page)
    plain_parts: list[str] = []
    hits: list[tuple[str, str, int]] = []          # (address, link text, position in the plain text)
    spans: list[tuple[int, int]] = []              # where every link's text sits in the plain text
    last = 0
    plain_len = 0
    for m in HREF_RE.finditer(text):
        before = " " + _text(text[last:m.start()]) + " "
        plain_parts.append(before)
        plain_len += len(before)
        label = _text(m.group(3))[:200]
        for u in _urls_in(m.group(2)):
            hits.append((u, label, plain_len))
        spans.append((plain_len, plain_len + len(label)))
        plain_parts.append(label)
        plain_len += len(label)
        last = m.end()
    plain_parts.append(" " + _text(text[last:]))
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

    def segments(at: int) -> tuple[str, str]:
        """The offer's text around a link: up to the next link (after), back to the previous one (before)."""
        i = next(k for k, sp in enumerate(spans) if sp[0] == at)
        end = spans[i][1]
        return (plain[max(at - WINDOW_BEFORE, spans[i - 1][1] if i else 0):at],
                plain[end:min(end + WINDOW_AFTER, spans[i + 1][0] if i + 1 < len(spans) else len(plain))])

    def clickout(url: str, label: str, at: int, pos: int) -> None:
        before, after = segments(at)
        if (rid := _named(label, names or [])):
            price = _first_price(after) or _first_price(before, last=True)
        elif CTA_RE.match(label.strip()) and (rid := _named(before, names or [], last=True)):
            price = _first_price(before, last=True)   # a row: [shop logo] [price] [to the shop →]
        else:
            return
        if not price:
            return
        css = css_of(f"{before} {label} {after}")
        cur = found.setdefault(rid, {})
        key = "#" + rid
        if key not in cur:
            cur[key] = {"url": None, "clickout": url, "title": "", "score": 0.0, "pos": pos, "price": price, "css": css}

    for pos, (raw, label, at) in enumerate(hits):
        try:
            url = normalize_url(raw)
        except ValueError:
            continue
        p = urlparse(url)
        host = (p.hostname or "").lower()
        path = p.path
        if names and at >= 0 and not any(_host_ok(url, d) for d in domains.values()) and \
                (NOT_SHOPS.search(host) or (own_domain and _host_ok(url, own_domain))):
            clickout(url, label, at, pos)                # a click-out of the comparison site: the shop by its name
            continue
        if len(path.strip("/")) < 3 or is_search_url(url) or ASSET_RE.search(path):
            continue
        words = f"{label} {slug_title(url)}".strip()
        if accessory_word(words, name):
            continue
        score = title_score(name, brand, words)[0] if name and words else 0.0
        ldo = ld.get(raw) or ld.get(url) or {}
        before, after = segments(at) if at >= 0 else ("", "")
        price = ldo.get("price") or _first_price(after) or _first_price(before, last=True)
        css = css_of(after) or css_of(before) or css_of(ldo.get("seller") or "")
        item = {"url": url, "title": label, "score": score, "pos": pos, "price": price, "css": css}
        rid = next((r for r, d in domains.items() if _host_ok(url, d)), None)
        if rid:
            key = url_key(rid, url) if url_key else path.lower()
            if key in skip:
                continue
            cur = found.setdefault(rid, {})
            if key not in cur or score > cur[key]["score"] or cur[key]["url"] is None:
                cur[key] = item
        elif host and url.startswith("https://") and public_host(host) and not NOT_SHOPS.search(host) \
                and not (own_domain and _host_ok(url, own_domain)) and price:
            dom = host.removeprefix("www.")
            if dom not in others or score > others[dom]["score"]:
                others[dom] = {**item, "domain": dom, "seller": ldo.get("seller")}
    by_shop = {rid: sorted(c.values(), key=lambda x: (-round(x["score"], 1), x["pos"])) for rid, c in found.items()}
    return by_shop, sorted(others.values(), key=lambda x: (-x["score"], x["pos"]))


def product_pages(page: str, own_domain: str, product: dict[str, Any]) -> list[str]:
    """Product pages on a comparison site's own domain in its search results, best match first: the page that lists
    every shop's price for that product. A title there is short ("Sony WH-1000XM5 Zwart"): it must name every model
    number of the product and cover at least half of its name, and must not be an accessory."""
    from .parsers import TITLE_DOUBT

    out: list[tuple[float, int, str]] = []
    for i, m in enumerate(HREF_RE.finditer(_flatten(page))):
        label = _text(m.group(3))
        for u in _urls_in(m.group(2)) or ([f"https://www.{own_domain}{m.group(2)}"] if m.group(2).startswith("/") else []):
            if not _host_ok(u, own_domain) or is_search_url(u) or ASSET_RE.search(urlparse(u).path):
                continue
            words = f"{label} {slug_title(u)}"
            if accessory_word(words, product.get("name")):
                continue
            score, missing = title_score(product.get("name"), product.get("brand"), words)
            if score >= TITLE_DOUBT and not missing and u not in [x[2] for x in out]:
                out.append((score, i, u))
    return [u for _s, _i, u in sorted(out, key=lambda x: (-x[0], x[1]))]


def extract(page: str, domains: dict[str, str], product: dict[str, Any] | None = None,
            skip: set[str] | frozenset[str] = frozenset(), url_key: Any = None) -> dict[str, list[dict[str, Any]]]:
    """Links to your shops in a finder's result page: {shop id: [{"url", "title", "score", "price", "css"}]}, best first."""
    return offers(page, domains, product, skip, url_key)[0]
