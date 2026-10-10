"""HTML price extraction per retailer, product identity and matching. Pure functions, regex only (no extra deps).

Retailer markup changes regularly; every parser therefore tries several strategies
(JSON-LD -> meta tags -> retailer specific markup) and returns None when unsure.

Matching a page to a product works on identity first (EAN / ISBN / model number), and on the title second:
a link is only trusted when the page proves it is the same product.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from .const import CATEGORIES, GENERIC_SHOPS
from .i18n import T
from .models import gtin_check, gtin_key, is_isbn, normalize_gtin, parse_price
from .shops import PROFILE, all_domains, reader_of, site_root


@dataclass
class Parsed:
    price: float | None
    title: str | None = None
    image: str | None = None
    blocked: bool = False
    unavailable: bool = False
    list_price: float | None = None      # the struck-through "was" price when the page has one
    reason: str | None = None            # why there is no price: "sold_out" or "discontinued" (no error, a warning)
    gtins: tuple[str, ...] = ()          # barcodes the page declares for its own product (EAN / UPC / ISBN)
    mpn: str | None = None               # manufacturer part / model number
    sku: str | None = None
    brand: str | None = None
    category: str | None = None          # the shop's own category text (JSON-LD category / breadcrumb)


# Why a shop page has no price. The structured availability (JSON-LD / schema.org) counts first; the words
# only when the page has no price at all (they can also appear in menus or translations of every page).
GONE_WORDS_RE = re.compile(r"niet meer (?:leverbaar|verkrijgbaar|beschikbaar|in (?:het )?assortiment)|uit (?:het )?assortiment|"
                           r"uit (?:de )?(?:handel|productie)|no longer (?:available|sold|in stock)|discontinued|"
                           r"nicht mehr (?:lieferbar|erhältlich|verfügbar)|aus dem sortiment|plus disponible|"
                           r"n'est plus (?:vendu|disponible|fabriqué)|ya no está disponible|descatalogado", re.I)
SOLD_OUT_WORDS_RE = re.compile(r"(?:tijdelijk )?uitverkocht|niet (?:op voorraad|leverbaar)|out of stock|sold out|"
                               r"(?:tijdelijk|momenteel) niet (?:beschikbaar|verkrijgbaar)|temporarily (?:unavailable|out of stock)|"
                               r"currently unavailable|ausverkauft|nicht (?:vorrätig|lieferbar|auf lager)|"
                               r"vorübergehend nicht (?:verfügbar|lieferbar)|temporairement (?:indisponible|en rupture)|épuisé|"
                               r"rupture de stock|agotado|sin stock", re.I)

BLOCK_MARKERS = (
    "api-services-support@", "Type the characters you see", "Voer de tekens in",
    "Geben Sie die Zeichen", "/errors/validateCaptcha", "captcha", "Access Denied",
    "Just a moment...", "Attention Required",
    "Pardon Our Interruption", "_Incapsula_Resource", "isImpervaSpaSupport", "Incapsula incident ID",
)
# a shop's protection against automated visits (a bot protection service): an unmistakable wall page, never
# a normal product page that merely mentions "captcha" somewhere. Seen on any shop, it means: blocked, leave it alone.
BOT_WALL_RE = re.compile(r"<title>\s*Pardon Our Interruption|_Incapsula_Resource|isImpervaSpaSupport|Incapsula incident ID"
                         r"|<title>\s*Just a moment\.\.\.|<title>\s*Attention Required! \| Cloudflare|/cdn-cgi/challenge-platform", re.I)


def bot_wall(page: str | None) -> bool:
    return bool(page) and bool(BOT_WALL_RE.search(page[:60000]))


# ---------------------------------------------------------------- structured data
def _jsonld_blocks(page: str):
    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            yield json.loads(raw.strip())
        except ValueError:
            continue


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _types(node: dict) -> list[Any]:
    t = node.get("@type")
    return t if isinstance(t, list) else [t]


def _text(v: Any) -> str | None:
    if isinstance(v, str):
        return htmllib.unescape(v).strip() or None
    if isinstance(v, dict):
        return _text(v.get("name") or v.get("@value"))
    if isinstance(v, list) and v:
        return _text(v[0])
    return None


def _product_nodes(page: str) -> list[dict]:
    return [n for b in _jsonld_blocks(page) for n in _walk(b) if "Product" in _types(n) or "Book" in _types(n)]


def _offer_prices(offers: Any) -> list[float]:
    prices = []
    for off in _walk(offers) if offers else []:
        if not isinstance(off, dict):
            continue
        avail = str(off.get("availability", ""))
        if "OutOfStock" in avail or "SoldOut" in avail or "Discontinued" in avail:
            continue
        for key in ("price", "lowPrice"):
            if (p := parse_price(off.get(key))) is not None:
                prices.append(p)
        spec = off.get("priceSpecification")
        for sp in spec if isinstance(spec, list) else [spec] if isinstance(spec, dict) else []:
            if "ListPrice" not in str(sp.get("priceType", "")) and "Strikethrough" not in str(sp.get("priceType", "")):
                if (p := parse_price(sp.get("price"))) is not None:
                    prices.append(p)
    return prices


def _list_prices(offers: Any) -> list[float]:
    out = []
    for off in _walk(offers) if offers else []:
        spec = off.get("priceSpecification") if isinstance(off, dict) else None
        for sp in spec if isinstance(spec, list) else [spec] if isinstance(spec, dict) else []:
            if "ListPrice" in str(sp.get("priceType", "")) or "Strikethrough" in str(sp.get("priceType", "")):
                if (p := parse_price(sp.get("price"))) is not None:
                    out.append(p)
    return out


def _node_gtins(node: dict) -> list[str]:
    out = []
    for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "isbn", "ean", "upc"):
        for v in node.get(key) if isinstance(node.get(key), list) else [node.get(key)]:
            if (g := normalize_gtin(v)) and g not in out:
                out.append(g)
    return out


GTIN_PATTERNS = (
    r'itemprop=["\'](?:gtin\d*|isbn|ean)["\'][^>]*?content=["\']([\d-]{8,17}[\dXx]?)["\']',
    r'content=["\']([\d-]{8,17}[\dXx]?)["\'][^>]*?itemprop=["\'](?:gtin\d*|isbn|ean)["\']',
    r'<meta[^>]+(?:property|name)=["\'](?:og:upc|og:ean|og:isbn|product:ean|product:gtin|book:isbn)["\'][^>]+content=["\']([\d-]{8,17}[\dXx]?)["\']',
    r'data-(?:ean|gtin|isbn|barcode)=["\']([\d-]{8,17}[\dXx]?)["\']',
    r'"(?:ean|gtin\d{0,2}|isbn|isbn13|barcode)"\s*:\s*"?([\d-]{8,17}[\dXx]?)"?',
    r'\bISBN(?:-1[03])?[:\s]*([\d-]{10,17}[\dXx]?)',
    r'\bEAN(?:-13)?[:\s]*([\d]{8,14})\b',
)


def _page_gtins(page: str, nodes: list[dict]) -> tuple[str, ...]:
    """Barcodes the page declares. The structured data of the page's own product counts first; the looser patterns
    (attributes, inline JSON, 'EAN: ...' text) only when the structured data names none."""
    out: list[str] = []
    for n in nodes[:3]:
        out += [g for g in _node_gtins(n) if g not in out]
    if out:
        return tuple(out)
    head = page[:600000]
    for pat in GTIN_PATTERNS:
        for m in re.finditer(pat, head, re.I):
            if (g := normalize_gtin(m.group(1))) and g not in out:
                out.append(g)
        if out:
            break
    return tuple(out[:3])


def _from_jsonld(page: str) -> Parsed | None:
    nodes = _product_nodes(page)
    for node in nodes:
        prices = _offer_prices(node.get("offers"))
        img = node.get("image")
        img = img[0] if isinstance(img, list) and img else img
        img = img.get("url") if isinstance(img, dict) else img
        if prices:
            lp = _list_prices(node.get("offers"))
            return Parsed(min(prices), _text(node.get("name")), img if isinstance(img, str) else None,
                          list_price=max(lp) if lp and max(lp) > min(prices) else None,
                          gtins=_page_gtins(page, [node]), mpn=_text(node.get("mpn")), sku=_text(node.get("sku")),
                          brand=_text(node.get("brand")), category=_text(node.get("category")))
    return None


def _identity(page: str, parsed: Parsed) -> Parsed:
    """Fill the identity fields (barcodes, model number, brand, category) of a parsed page from its structured data."""
    nodes = _product_nodes(page)
    if not parsed.gtins:
        parsed.gtins = _page_gtins(page, nodes)
    if nodes:
        n = nodes[0]
        parsed.mpn = parsed.mpn or _text(n.get("mpn"))
        parsed.sku = parsed.sku or _text(n.get("sku"))
        parsed.brand = parsed.brand or _text(n.get("brand"))
        parsed.category = parsed.category or _text(n.get("category"))
        if not parsed.title:
            parsed.title = _text(n.get("name"))
    parsed.brand = parsed.brand or _meta(page, "product:brand", "og:brand")
    parsed.category = parsed.category or _breadcrumb(page)
    return parsed


def _breadcrumb(page: str) -> str | None:
    """The category path of a page, from its BreadcrumbList ('Home > Electronics > Laptops')."""
    for block in _jsonld_blocks(page):
        for n in _walk(block):
            if "BreadcrumbList" in _types(n) and isinstance(n.get("itemListElement"), list):
                names = []
                for el in n["itemListElement"]:
                    if isinstance(el, dict):
                        item = el.get("item")
                        nm = _text(el.get("name")) or (_text(item.get("name")) if isinstance(item, dict) else None)
                        if nm:
                            names.append(nm)
                if names:
                    return " > ".join(names[:6])
    return None


def _meta(page: str, *props: str) -> str | None:
    for prop in props:
        m = re.search(
            rf'<meta[^>]+(?:property|name|itemprop)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']', page, re.I
        ) or re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name|itemprop)=["\']{re.escape(prop)}["\']', page, re.I
        )
        if m:
            return htmllib.unescape(m.group(1))
    return None


def _title(page: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    return htmllib.unescape(m.group(1)).strip() if m else None


def _own_product_availability(page: str) -> str | None:
    """The schema.org availability of the page's own (first top-level) product. Recommendations nested in it or
    elsewhere don't count. Returns "" when the product is there but says nothing, None without a product."""
    tops = []
    for block in _jsonld_blocks(page):
        for node in (block.get("@graph") if isinstance(block, dict) and isinstance(block.get("@graph"), list)
                     else block if isinstance(block, list) else [block]):
            if isinstance(node, dict) and ("Product" in _types(node) or "Book" in _types(node)):
                tops.append(node)
    if not tops:
        return None
    offers = tops[0].get("offers")
    offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
    avail = " ".join(str(o.get("availability") or "") for o in offers if isinstance(o, dict))
    return avail or ""


def availability_reason(page: str) -> str | None:
    """'discontinued', 'sold_out' or None for a page without a price. The structured availability of the
    page's own product decides first; without one, the words on the page."""
    own = _own_product_availability(page)
    if own is not None:
        if not own:
            return None                                 # the product is there but says nothing: no guessing from text
        if "Discontinued" in own:
            return "discontinued"
        if "OutOfStock" in own or "SoldOut" in own:
            return "sold_out"
        return None                                     # in stock / pre-order: no reason to call it unavailable
    text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", page[:600000], flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    if GONE_WORDS_RE.search(text):
        return "discontinued"
    if SOLD_OUT_WORDS_RE.search(text):
        return "sold_out"
    return None


# ------------------------------------------------------------------- readers
def parse_generic(page: str) -> Parsed:
    if (p := _from_jsonld(page)) is not None:
        return p
    price = parse_price(_meta(page, "product:price:amount", "og:price:amount", "price"))
    return Parsed(price, _meta(page, "og:title") or _title(page), _meta(page, "og:image"))


def parse_marketplace(page: str) -> Parsed:
    if any(marker.lower() in page[:200000].lower() for marker in BLOCK_MARKERS[:6]):
        return Parsed(None, blocked=True)
    title = None
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', page, re.S)
    if m:
        title = htmllib.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    image = None
    m = re.search(r'"hiRes"\s*:\s*"(https:[^"]+)"', page) or re.search(r'id="landingImage"[^>]+src="([^"]+)"', page)
    if m:
        image = m.group(1)
    price = buybox_price(page)
    if price is not None:
        return Parsed(price, title, image)
    unavailable = bool(re.search(r'id="outOfStock"|Momenteel niet verkrijgbaar|Derzeit nicht verfügbar|Currently unavailable', page))
    return Parsed(None, title, image, unavailable=unavailable)


BUYBOX_IDS = ("corePriceDisplay_desktop_feature_div", "corePrice_feature_div", "apex_desktop",
              "corePrice_desktop", "buybox", "desktop_buybox", "newAccordionRow")


def _offscreen_prices(block: str) -> list[float]:
    """Prices inside a block, skipping struck-through list prices (a-text-price / data-a-strike)."""
    out = []
    for cls, inner in re.findall(r'<span class="(a-price[^"]*)"[^>]*>(.*?)</span>\s*</span>', block, re.S):
        if "a-text-price" in cls or "a-size-small" in cls:
            continue
        m = re.search(r'class="a-offscreen"[^>]*>([^<]+)', inner)
        if m and (p := parse_price(m.group(1))):
            out.append(p)
    return out


def buybox_price(page: str) -> float | None:
    """The price in the buy box, never just the first price on the page (that can be an
    accessory, a unit price, a coupon or a struck-through list price)."""
    for pat in (r'name="items\[0\.base\]\[customerVisiblePrice\]\[amount\]"\s+value="([\d.]+)"',
                r'id="twister-plus-price-data-price"\s+value="([\d.]+)"',
                r'"priceToPay"\s*:\s*\{[^{}]*?"(?:amount|price)"\s*:\s*"?([\d.]+)',
                r'"desktop_buybox_group_1"\s*:\s*\[\s*\{[^\]]*?"priceAmount"\s*:\s*([\d.]+)'):
        m = re.search(pat, page)
        if m and (p := parse_price(float(m.group(1)))):
            return p
    for bid in BUYBOX_IDS:
        i = page.find(f'id="{bid}"')
        if i < 0:
            continue
        block = page[i:i + 8000]
        m = re.search(r'class="a-price[^"]*priceToPay[^"]*"[^>]*>.*?class="a-offscreen"[^>]*>([^<]+)<', block, re.S)
        if m and (p := parse_price(m.group(1))):
            return p
        if prices := _offscreen_prices(block):
            return prices[0]
    for pid in ("priceblock_dealprice", "priceblock_ourprice", "priceblock_saleprice", "price_inside_buybox",
                "newBuyBoxPrice", "kindle-price"):
        m = re.search(rf'id="{pid}"[^>]*>\s*([^<]+)<', page)
        if m and (p := parse_price(m.group(1))):
            return p
    return None


def parse_retail(page: str) -> Parsed:
    if "Access Denied" in page[:2000]:
        return Parsed(None, blocked=True)
    if (p := _from_jsonld(page)) is not None:
        return p
    for pattern in (
        r'"price"\s*:\s*\{[^}]*?"value"\s*:\s*([\d.]+)',
        r'"priceValue"\s*:\s*"?([\d.]+)',
        r'itemprop="price"[^>]*content="([\d.,]+)"',
    ):
        m = re.search(pattern, page)
        if m and (price := parse_price(m.group(1))):
            return Parsed(price, _meta(page, "og:title") or _title(page), _meta(page, "og:image"))
    return Parsed(parse_price(_meta(page, "product:price:amount", "og:price:amount")),
                  _meta(page, "og:title") or _title(page), _meta(page, "og:image"))


def _brand(domain: str) -> str:
    """The name part of a domain: shop.co.uk, shop.com.be and shop.fr -> 'shop'."""
    parts = domain.lower().removeprefix("www.").split(".")
    return parts[-3] if len(parts) >= 3 and parts[-2] in ("co", "com") else parts[-2] if len(parts) >= 2 else parts[0]


def is_marketplace(retailer: str) -> bool:
    """A shop read as "marketplace", also a shop you add yourself on another country site of the same marketplace
    (same name, other country domain)."""
    from .shops import domain_of

    if reader_of(retailer) == "marketplace":
        return True
    dom = domain_of(retailer)
    if not dom or retailer in PROFILE:
        return False
    return any(_brand(dom) == _brand(s["domain"]) for s in PROFILE.values() if s["reader"] == "marketplace")


def parse_page(retailer: str, page: str) -> Parsed:
    """What a shop page says: price, title, image, and the identity of its product (barcodes, model number, brand)."""
    if bot_wall(page):                             # the shop doesn't want automated visits: blocked, never "no price"
        return Parsed(None, blocked=True)
    market = is_marketplace(retailer)
    parser = parse_marketplace if market else parse_retail if reader_of(retailer) == "retail" else parse_generic
    result = parser(page)
    if market and result.price is None and not result.blocked:
        # a marketplace page without a price in the buy box: not in stock (there), never an error
        result.unavailable, result.reason = True, "sold_out"
        return _identity(page, result)
    if result.price is None and not result.blocked and not result.unavailable:
        fallback = parse_generic(page)
        if fallback.price is not None:
            return _identity(page, fallback)
    if result.price is None and not result.blocked and (result.unavailable or result.title) and not result.reason:
        # no price: say why when the page says so (sold out / no longer sold); a warning, not an error
        if (why := availability_reason(page)) or result.unavailable:
            result.unavailable, result.reason = True, why or "sold_out"
    return _identity(page, result)


# --------------------------------------------------------------- URL handling
TRACKING_PARAMS = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|ref|ref_|tag|affiliate\w*|aff\w*|campaign\w*|cmpid|sid|source)$", re.I)


def normalize_url(url: str) -> str:
    """A product address without fragment and tracking parameters."""
    value = url.strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("Provide a full product URL.")
    parts = urlsplit(value)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def product_code_url(retailer: str, asin: str) -> str:
    from .shops import domain_of

    domain = (domain_of(retailer) or "").removeprefix("www.")
    return f"https://www.{domain}/dp/{asin}"


def retailer_from_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for rid, dom in all_domains().items():
        if host == dom or host.endswith("." + dom):
            return rid
    return None


def url_key(retailer: str, url: str) -> str:
    """Stable identity of a product page (product code (ASIN) for a marketplace, path without query otherwise)."""
    if is_marketplace(retailer):
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
        if m:
            return m.group(1)
    return urlparse(url).path.rstrip("/").lower()


def is_search_url(url: str | None) -> bool:
    """A shop's search results page (not a product page)."""
    if not url or not url.startswith("http"):
        return False
    u = urlparse(url)
    return bool(re.search(r"/(?:search|zoeken|zoek|suche|recherche|buscar|s)(?:/|$)|/search\b", u.path, re.I)
                or re.search(r"(?:^|&)(?:q|text|query|searchtext|search|k|keyword|zoekterm)=", u.query, re.I)) \
        and not re.search(r"/(?:p|dp|product|gp/product)/", u.path)


def slug_title(url: str) -> str:
    """Many shops carry the product name in the path (/p/<name>/<id>/); numbers-only segments are skipped."""
    parts = [p for p in urlparse(url).path.split("/") if p and not re.fullmatch(r"[\d]+|p|dp|product|producten?|nl|be|fr|de|en", p, re.I)]
    return " ".join(re.sub(r"[-_+]+", " ", p) for p in parts[-2:])


# ------------------------------------------------------------ product matching
# Words that make a product title an accessory of the product rather than the product itself. Only counts when the
# product's own name doesn't contain the word (a phone case is not the phone; a "case" in a case study is not an issue).
ACCESSORY_RE = re.compile(
    r"\b(hoes|hoesje|hoesjes|case|cases|cover|covers|etui|schutzh[uü]lle|housse|funda|"
    r"screen ?protectors?|beschermfolie|schermbeschermer|displayschutz|folie|tempered|"
    r"oplader|lader|charger|charging|adapter|adaptor|kabel|cable|snoer|"
    r"houder|holder|stand|beugel|mount|wandhalter|halterung|"
    r"tas|bag|sleeve|pouch|strap|bandje|polsband|armband|"
    r"sticker|stickers|aufkleber|skin|poster|"
    r"vervang\w*|replacement|spare|ersatz\w*|reserve ?onderdel\w*|onderdelen|refill|navulling|"
    r"batterij|batterijen|battery|accu|oorkussen\w*|ear ?pads?|ear ?cushions?|"
    r"handleiding|manual|instructions only|anleitung|"
    r"compatibel|compatible|kompatibel|geschikt\s+(?:voor|met|bij)|suitable\s+for|passend\s+(?:f[uü]r|zu|bei)|"
    r"voor\s+(?:de\s+)?[a-z]\w+ ?\d|for\s+[a-z]\w+ ?\d)\b", re.I)

# Dutch and German glue words together: "Beschermhoes", "Displayfolie", "Autolader": an accessory word at the end of a longer word
COMPOUND_ACCESSORY_RE = re.compile(r"\b\w{3,}(?:hoes|hoesje|hoesjes|tasje|folie|houder|beugel|lader|oplader|kabel|snoer|sleeve|etui|halterung|schutzh[uü]lle)\b", re.I)

# your own words (Manage → Settings → Product filter): extra words that are never the product, and exceptions
_USER_BLOCK: re.Pattern | None = None
_USER_ALLOW: re.Pattern | None = None


def _word_re(words: list[str]) -> re.Pattern | None:
    """Whole words / phrases, case-insensitive; a trailing * matches any ending ('verlicht*')."""
    parts = []
    for w in words:
        w = re.sub(r"\s+", " ", str(w)).strip()
        if not w:
            continue
        star = w.endswith("*")
        body = r"\s+".join(re.escape(x) for x in w.rstrip("*").split(" "))
        parts.append(rf"(?<!\w){body}{r'\w*' if star else r'(?!\w)'}")
    return re.compile("|".join(parts), re.I) if parts else None


def set_custom_words(block: list[str] | None, allow: list[str] | None) -> None:
    global _USER_BLOCK, _USER_ALLOW
    _USER_BLOCK, _USER_ALLOW = _word_re(block or []), _word_re(allow or [])


# the built-in list in readable form (shown in the settings)
BUILTIN_WORDS = ("hoes(je)", "case", "cover", "screen protector", "beschermfolie", "oplader", "lader", "kabel", "adapter",
                 "houder", "standaard", "beugel", "tas", "sleeve", "polsband", "sticker", "vervang*", "replacement",
                 "onderdelen", "navulling", "batterij", "accu", "handleiding", "compatibel", "geschikt voor …", "for …")


def accessory_word(title: str | None, product_name: str | None = None) -> str | None:
    """The word that makes a title an accessory (not the product itself), or None. Words that are in the product's own
    name don't count, nor do your exceptions; your own words always do."""
    if not title:
        return None
    t = htmllib.unescape(title)
    if _USER_ALLOW:
        t = _USER_ALLOW.sub(" ", t)
    if _USER_BLOCK and (m := _USER_BLOCK.search(t)):
        return m.group(0)
    own = (product_name or "").lower()
    for rx in (ACCESSORY_RE, COMPOUND_ACCESSORY_RE):
        for m in rx.finditer(t):
            word = m.group(0)
            if word.lower() not in own and not re.search(rf"(?<!\w){re.escape(word.lower())}", own):
                return word
    return None


STOPWORDS = frozenset("""de het een en of met voor van in op te bij naar the and or with for of in on to by a an von und mit fuer fur der die das
ein eine le la les un une des du et pour avec sur el los las y con para por di il lo e per new nieuw neu nouveau nuevo
nl be fr de en eu pcs stuks st piece pieces set pack""".split())
COLORS = frozenset("""zwart wit rood blauw groen geel grijs grey gray roze paars oranje bruin zilver goud black white red blue green yellow pink
purple orange brown silver gold schwarz weiss weiß rot blau grun gruen gelb grau rosa lila braun silber noir blanc rouge bleu vert jaune gris
rose violet marron argent or negro blanco rojo azul verde amarillo gris plata midnight starlight titanium space graphite""".split())


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", htmllib.unescape(text or "")).encode("ascii", "ignore").decode().lower()


def tokens(text: str | None) -> list[str]:
    """Significant words of a product title: lowercase, no accents, no filler words or colours."""
    out = []
    for t in re.findall(r"[a-z0-9]+", _fold(text or "")):
        if t in STOPWORDS or t in COLORS or len(t) < 2 and not t.isdigit():
            continue
        if t not in out:
            out.append(t)
    return out


def _has_digit(t: str) -> bool:
    return any(c.isdigit() for c in t)


def title_score(product_name: str | None, brand: str | None, candidate: str | None) -> tuple[float, list[str]]:
    """(0..1, missing model tokens): how well a candidate title covers the product's name. Model numbers (tokens with a
    digit) weigh double and must all be present, also when the candidate writes them with spaces ('256 GB')."""
    want = tokens(f"{brand or ''} {product_name or ''}") if brand and _fold(brand) not in _fold(product_name or "") \
        else tokens(product_name)
    if not want or not candidate:
        return 0.0, []
    have = set(tokens(candidate))
    squashed = re.sub(r"[^a-z0-9]", "", _fold(candidate))
    total = got = 0.0
    missing: list[str] = []
    for t in want:
        w = 2.0 if _has_digit(t) else 1.0
        total += w
        if t in have or (len(t) >= 3 and _has_digit(t) and t in squashed) or (len(t) >= 4 and t in squashed and not _has_digit(t)):
            got += w
        elif _has_digit(t):
            missing.append(t)
    score = got / total if total else 0.0
    # extra model numbers in the candidate that are not in the product: probably another model of the same line
    extra = [t for t in have - set(want) if _has_digit(t) and len(t) >= 3 and not re.fullmatch(r"(19|20)\d\d|\d+(gb|tb|mb|mm|cm|ml|l|kg|g|w|hz|v)?", t)
             and not any(t in w or w in t for w in want)]
    if extra and any(_has_digit(w) for w in want):
        score *= 0.85
    return round(score, 3), missing


def mpn_match(mpn: str | None, *texts: str | None) -> bool:
    """The model number appears in one of the texts (ignoring case, spaces and dashes)."""
    m = re.sub(r"[^a-z0-9]", "", _fold(mpn or ""))
    return len(m) >= 4 and any(m in re.sub(r"[^a-z0-9]", "", _fold(t or "")) for t in texts)


TITLE_OK = 0.75        # the title covers the product's name this well: the same product
TITLE_DOUBT = 0.5      # below: another product; between: a doubt the user can decide on


def product_match(product: dict[str, Any], parsed: Parsed | None, url: str = "") -> tuple[str | None, str]:
    """('ok' | 'suspect' | None, reason): is this page the product? None = nothing to judge yet.
    Identity first: the barcode, then the model number; then the title (with accessories ruled out)."""
    if parsed is None:
        return None, T("no product title yet")
    title = parsed.title or slug_title(url)
    name = product.get("name") or ""
    ean = gtin_key(product.get("ean"))
    page_keys = {k for g in parsed.gtins if (k := gtin_key(g))}
    if (word := accessory_word(title, name)):
        return "suspect", T("looks like an accessory ({word})", word=word)
    if ean and page_keys:
        if ean in page_keys:
            return "ok", T("barcode (EAN) matches")
        if product.get("mpn") and mpn_match(product["mpn"], parsed.mpn, title):
            return "ok", T("model number matches")
        return "suspect", T("other barcode on the page ({ean})", ean=next(iter(parsed.gtins)))
    if product.get("mpn") and mpn_match(product["mpn"], parsed.mpn, title, parsed.sku):
        return "ok", T("model number matches")
    if not title:
        return None, T("no product title yet")
    if not name:
        return None, T("the product has no name yet")
    score, missing = title_score(name, product.get("brand"), title)
    if missing:
        return "suspect", T("model number {number} is not in the title", number=missing[0].upper())
    if score >= TITLE_OK:
        return "ok", T("title matches ({pct}%)", pct=round(score * 100))
    if score >= TITLE_DOUBT:
        return "suspect", T("title only partly matches ({pct}%)", pct=round(score * 100))
    return "suspect", T("title does not match ({pct}%)", pct=round(score * 100))


def wrong_product(product: dict[str, Any], parsed: Parsed | None) -> str | None:
    """Why a page is clearly another product (an accessory, another barcode), or None. Only these reasons make a
    link go away by itself; a title that merely differs stays a doubt for the user to decide."""
    if parsed is None:
        return None
    title, name = parsed.title or "", product.get("name") or ""
    if (word := accessory_word(title, name)):
        return T("looks like an accessory ({word})", word=word)
    ean = gtin_key(product.get("ean"))
    keys = {k for g in parsed.gtins if (k := gtin_key(g))}
    if ean and keys and ean not in keys and not (product.get("mpn") and mpn_match(product["mpn"], parsed.mpn, title)):
        return T("other barcode on the page ({ean})", ean=next(iter(parsed.gtins)))
    return None


def link_check(offer: dict[str, Any], product: dict[str, Any]) -> tuple[str | None, str]:
    """Is this shop link the right product? Uses what the page said (barcode, model number, title or URL slug).

    Returns (status, reason) with status 'ok', 'suspect' or None (cannot judge yet).
    A manual 'confirmed' is never overridden."""
    if offer.get("link_status") == "confirmed":
        return "confirmed", T("confirmed by hand")
    if offer.get("url") and offer.get("url") == product.get("source_url"):
        return "ok", T("the address you added the product with")
    parsed = None
    if offer.get("title") or offer.get("gtins"):
        parsed = Parsed(None, offer.get("title"), gtins=tuple(offer.get("gtins") or ()), mpn=offer.get("mpn"))
    status, reason = product_match(product, parsed, offer.get("url") or "") if parsed else (None, "")
    if status is None and offer.get("url"):
        slug = slug_title(offer["url"])
        if slug and product.get("name"):
            status, reason = product_match(product, Parsed(None, slug), "")
            reason = T("URL: {reason}", reason=reason)
            if status == "ok":
                status, reason = None, T("no product title yet (filled in at the next price check)")
    if status == "suspect":
        return status, reason
    ref = product.get("ref_price")
    low = min((p for _, p in offer.get("history", [])), default=None)
    if ref and low is not None and low < ref * 0.3:
        return "suspect", T("price €{price} is far too low for this product (reference price €{ref})", price=f"{low:.2f}", ref=f"{ref:.2f}")
    if status is None:
        return None, T("no product title yet (filled in at the next price check)")
    return status, reason


def clean_title(title: str) -> str:
    """'Sony WH-1000XM5 Draadloze koptelefoon - Zwart | bol' -> 'Sony WH-1000XM5 Draadloze koptelefoon'."""
    t = htmllib.unescape(title or "").strip()
    t = re.split(r"\s[|•]\s", t)[0]
    names = {n.lower() for rid in PROFILE for n in (PROFILE[rid]["name"], _brand(PROFILE[rid]["domain"]))}
    for shop in sorted(names, key=len, reverse=True):
        t = re.sub(rf"\s*(?::|\s-|\s–)\s*{re.escape(shop)}\S*\s*$", "", t, flags=re.I)
        t = re.sub(rf"^\s*{re.escape(shop)}\S*\s*(?::|-|–)\s*", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–:")
    return t[:160] or (title or "")[:160]


# ------------------------------------------------------------- category guess
CATEGORY_WORDS: dict[str, re.Pattern] = {
    "books": re.compile(r"\b(boek|boeken|book|books|roman|thriller|kinderboek|stripboek|strip|literatuur|livre|livres|buch|buecher|bücher|"
                        r"libro|paperback|hardcover|gebonden|isbn|e-?reader|jeugdboek|kookboek|studieboek)\b", re.I),
    "electronics": re.compile(r"\b(elektronica|electronics|elektronik|electro|laptop|notebook|smartphone|gsm|telefoon|phone|tablet|tv|televisie|"
                              r"televisions?|audio|koptelefoon|headphones?|speaker|camera|computer|pc|monitor|printer|console|gaming pc|"
                              r"wasmachine|koelkast|droger|vaatwasser|stofzuiger|haartrekker|smartwatch|wearables?|netwerk|router|"
                              r"informatica|image-?son|haushaltsger[aä]te|appliances?|huishoudelijke apparaten)\b", re.I),
    "toys_games": re.compile(r"\b(speelgoed|toys?|spielzeug|jouets?|jeux|spel|spellen|games?|gaming|puzzel|puzzle|bordspel|board ?game|"
                             r"lego|playmobil|poppen|barbie|knuffel|constructie|bouwset|videogames?)\b", re.I),
    "home_garden_diy": re.compile(r"\b(tuin|garden|garten|jardin|huis|home|wonen|woonaccessoires|keuken|kitchen|badkamer|bathroom|meubel|"
                                  r"meubels|furniture|bricolage|doe-?het-?zelf|diy|gereedschap|tools?|werkzeug|outillage|verf|paint|"
                                  r"verlichting|lighting|decoratie|slaapkamer|woonkamer|barbecue|bbq|zwembad|haard)\b", re.I),
}


def guess_category(*texts: str | None, ean: str | None = None) -> str | None:
    """The product category from the shop's own category text / breadcrumb / title; an ISBN means a book."""
    if ean and is_isbn(ean):
        return "books"
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    hits = {c: len(rx.findall(blob)) for c, rx in CATEGORY_WORDS.items()}
    best = max(hits, key=lambda c: hits[c])
    return best if hits[best] else None


def product_identity(parsed: Parsed, url: str) -> dict[str, Any]:
    """What a product page tells about the product (for adding a product by address)."""
    ean = next((g for g in parsed.gtins if gtin_check(g) or is_isbn(g)), None)
    return {"name": clean_title(parsed.title) if parsed.title else slug_title(url).title(), "brand": parsed.brand,
            "ean": ean, "mpn": parsed.mpn, "image": parsed.image, "price": parsed.price,
            "category": guess_category(parsed.category, parsed.title, ean=ean)}


# --------------------------------------------------------------- search results
NAV_PATH_RE = re.compile(r"/(?:(?:add-?to-?)?cart|basket|winkelwagen|winkelmand(?:je)?|mandje|warenkorb|panier|login|logout|(?:my-?)?account|"
                         r"wish-?list|wishlist|verlanglijst(?:je)?|merkliste|compare|vergelijk(?:en)?|reviews?|"
                         r"beoordelingen|share|delen|help|klantenservice|contact|over-ons|about|blog|actie|acties|cadeau)(?:\.\w+)?(?:/|$)", re.I)
ASSET_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|svg|css|js|pdf|json|xml|ico)(?:\?|$)", re.I)


def _marketplace_results(page: str) -> list[tuple[str, str]]:
    out = []
    for asin, chunk in re.findall(r'data-asin="(B[0-9A-Z]{9}|\d{9}[\dX])"(.*?)(?=data-asin="(?:B[0-9A-Z]{9}|\d{9}[\dX])"|$)', page, re.S):
        m = (re.search(r"<h2[^>]*>(.*?)</h2>", chunk, re.S) or re.search(r'aria-label="([^"]+)"', chunk)
             or re.search(r'class="[^"]*a-text-normal[^"]*"[^>]*>(.*?)<', chunk, re.S))
        if m:
            out.append((asin, re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()))
    return out


def _ld_results(page: str, domain: str) -> list[tuple[str, str]]:
    """Product links with names from the page's structured data (ItemList / Product)."""
    out = []
    for block in _jsonld_blocks(page):
        for n in _walk(block):
            if "Product" in _types(n) or "Book" in _types(n):
                url, name = _text(n.get("url")) or _text(n.get("@id")), _text(n.get("name"))
                if url and name and url.startswith(("http", "/")):
                    out.append((url, name))
            elif "ListItem" in _types(n) and isinstance(n.get("item"), dict):
                it = n["item"]
                url, name = _text(it.get("url")) or _text(it.get("@id")), _text(it.get("name")) or _text(n.get("name"))
                if url and name:
                    out.append((url, name))
    return out


def _absolute(href: str, domain: str) -> str | None:
    href = htmllib.unescape(href.strip())
    if href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("http"):
        host = (urlparse(href).hostname or "").lower()
        return href if host == domain or host.endswith("." + domain) or domain.endswith("." + host) else None
    return f"https://www.{domain}{href if href.startswith('/') else '/' + href}"


def search_candidates(retailer: str, page: str, product: dict[str, Any],
                      skip: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Product pages in a shop's search results, best first: [{"url", "title", "score"}]. The score is how well the
    result's title (link text, picture text, structured data, the words in the address) covers the product's name;
    the caller decides which score is enough and checks the product page itself before trusting it."""
    from .shops import domain_of

    domain = (domain_of(retailer) or "").removeprefix("www.")
    name, brand = product.get("name") or "", product.get("brand")
    seen: dict[str, dict[str, Any]] = {}

    def add(url: str | None, title: str) -> None:
        if not url or ASSET_RE.search(urlparse(url).path):
            return
        url = url.split("#")[0]
        if retailer and url_key(retailer, url) in skip:
            return
        path = urlparse(url).path
        low = url.lower()
        if NAV_PATH_RE.search(path) or is_search_url(url) or any(w in low for w in ("/cart", "/login", "/c/", "wishlist", "/search")):
            return
        if path.strip("/") == "":
            return
        title = re.sub(r"\s+", " ", title).strip()
        text = f"{title} {slug_title(url)}"
        if accessory_word(text, name):
            return
        score, _missing = title_score(name, brand, text)
        key = url_key(retailer, url) if retailer else path
        if key not in seen or score > seen[key]["score"]:
            seen[key] = {"url": url, "title": title or slug_title(url), "score": score}

    if is_marketplace(retailer):
        for code, title in _marketplace_results(page):
            add(product_code_url(retailer, code), title)
    for url, title in _ld_results(page, domain):
        add(_absolute(url, domain), title)
    for attrs, inner in re.findall(r"<a\b([^>]*)>(.*?)</a>", page[:1500000], re.S | re.I):
        h = re.search(r'href="([^"]+)"', attrs)
        url = _absolute(h.group(1), domain) if h else None
        if not url:
            continue
        label = re.sub(r"<img[^>]+alt=\"([^\"]*)\"[^>]*>", r" \1 ", inner)
        label = htmllib.unescape(re.sub(r"<[^>]+>", " ", label))
        titled = re.search(r'\b(?:title|aria-label)="([^"]+)"', attrs)
        add(url, f"{label} {htmllib.unescape(titled.group(1)) if titled else ''}")
    return sorted(seen.values(), key=lambda c: -c["score"])[:12]
