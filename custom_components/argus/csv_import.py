"""CSV import of products: a table with (at least) a product address or a name. Understands the layout `export_csv`
writes (so export -> import round-trips) and loose spreadsheets: column names are matched by their meaning, in
English or Dutch, in any order. Pure functions; the coordinator adds the products one by one (politely)."""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from .const import CATEGORIES
from .i18n import LocalizedError, T
from .models import normalize_gtin, parse_price

MAX_ROWS = 500
MAX_BYTES = 1_000_000
ALIASES: dict[str, tuple[str, ...]] = {
    "url": ("url", "link", "address", "adres", "webadres", "product url", "product link", "page"),
    "name": ("name", "naam", "title", "titel", "product", "productnaam", "omschrijving", "description"),
    "category": ("category", "categorie", "type", "soort", "afdeling"),
    "ean": ("ean", "gtin", "isbn", "barcode", "ean13", "upc"),
    "brand": ("brand", "merk", "fabrikant", "manufacturer"),
    "mpn": ("model", "mpn", "modelnummer", "model number", "artikelnummer", "sku", "type number"),
    "ref_price": ("reference price", "referentieprijs", "price", "prijs", "adviesprijs", "list price", "rrp", "msrp"),
    "target_price": ("target price", "doelprijs", "doelbedrag", "target", "wishprice", "gewenste prijs", "max price"),
    "priority": ("priority", "prioriteit", "stars", "sterren"),
    "notes": ("notes", "notities", "opmerkingen", "note", "comments"),
}
CATEGORY_WORDS = {
    "electronics": ("electronics", "elektronica", "elektro", "electro", "tech"),
    "books": ("books", "boeken", "boek", "book"),
    "toys_games": ("toys & games", "toys", "games", "speelgoed", "spelletjes", "spellen", "toys_games"),
    "home_garden_diy": ("home, garden & diy", "huis", "tuin", "diy", "doe-het-zelf", "home", "garden", "home_garden_diy"),
    "other": ("other", "overig", "andere"),
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _category(value: str) -> str | None:
    v = _norm(value)
    for key, words in CATEGORY_WORDS.items():
        if v == key or v in {_norm(w) for w in words}:
            return key
    return None


def analyze_csv(text: str) -> dict[str, Any]:
    """Which column means what, and how many rows can be imported."""
    if len(text.encode("utf-8", errors="ignore")) > MAX_BYTES:
        raise LocalizedError("The file is too large (at most {mb} MB).", mb=MAX_BYTES // 1_000_000)
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise LocalizedError("The file is empty.")
    header = [_norm(c) for c in rows[0]]
    mapping: dict[str, int] = {}
    for field, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in {_norm(n) for n in names} and i not in mapping.values():
                mapping[field] = i
                break
    if "url" not in mapping and "name" not in mapping:
        raise LocalizedError("No column with the product address or the name found (give the first row column names such as URL and Name).")
    return {"mapping": mapping, "rows": rows[1:MAX_ROWS + 1], "columns": rows[0], "count": min(len(rows) - 1, MAX_ROWS),
            "truncated": len(rows) - 1 > MAX_ROWS}


def importable_rows(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Clean product dicts from the analysed rows (bad cells are skipped, not fatal)."""
    m, out = analysis["mapping"], []
    for raw in analysis["rows"]:
        def cell(field: str) -> str:
            i = m.get(field)
            v = raw[i].strip() if i is not None and i < len(raw) else ""
            return v[1:] if v[:1] == "'" and v[1:2] in ("=", "+", "-", "@", "'") else v   # formula-injection guard of the export
        url = cell("url")
        if url and not url.startswith(("http://", "https://")):
            url = ""
        item: dict[str, Any] = {"url": url or None, "name": cell("name") or None, "brand": cell("brand") or None,
                                "mpn": cell("mpn") or None, "notes": cell("notes")[:500] or None}
        if not item["url"] and not item["name"] and not cell("ean"):
            continue
        if (g := normalize_gtin(cell("ean"))):
            item["ean"] = g
        if (c := _category(cell("category"))):
            item["category"] = c
        for key in ("ref_price", "target_price"):
            if (v := parse_price(cell(key))) is not None:
                item[key] = v
        pr = cell("priority").count("★") or (int(cell("priority")) if cell("priority").isdigit() else 0)
        if pr in (1, 2, 3):
            item["priority"] = pr
        out.append(item)
    return out
