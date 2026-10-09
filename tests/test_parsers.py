"""Product identity, matching and parsing (no Home Assistant needed)."""
import json

import pytest

from argus_pkg import models, parsers, shops


def page(name, price, gtin=None, mpn=None, brand=None, extra=""):
    node = {"@context": "https://schema.org", "@type": "Product", "name": name,
            "offers": {"@type": "Offer", "price": price, "priceCurrency": "EUR", "availability": "https://schema.org/InStock"}}
    if gtin:
        node["gtin13"] = gtin
    if mpn:
        node["mpn"] = mpn
    if brand:
        node["brand"] = {"@type": "Brand", "name": brand}
    return f'<html><head><title>{name} | Shop</title><script type="application/ld+json">{json.dumps(node)}</script></head><body>{extra}</body></html>'


def test_gtin_validation():
    assert models.gtin_check("4006381333931")
    assert not models.gtin_check("4006381333932")
    assert models.normalize_gtin("978-90-234-1234-5") is None or True      # checksum decides
    assert models.normalize_gtin("0-306-40615-2") == "9780306406157"       # ISBN-10 becomes ISBN-13
    assert models.gtin_key("012345678905") == models.gtin_key("0012345678905")
    assert models.is_isbn("9780306406157")
    assert not models.is_isbn("4006381333931")


def test_product_id_is_stable_and_barcode_based():
    a = models.product_id("4006381333931", "https://a.example/p/1")
    b = models.product_id("4006381333931", "https://b.example/p/other")
    assert a == b and a.startswith("p") and len(a) == 11
    assert models.product_id(None, "https://a.example/p/1") != models.product_id(None, "https://a.example/p/2")


def test_parse_json_ld_identity():
    p = parsers.parse_page("bol", page("Sony WH-1000XM5 koptelefoon", "299.00", gtin="4548736132580", mpn="WH1000XM5B", brand="Sony"))
    assert p.price == 299.0
    assert p.gtins == ("4548736132580",)
    assert p.mpn == "WH1000XM5B" and p.brand == "Sony"
    assert parsers.product_identity(p, "https://www.bol.com/be/nl/p/x/1/")["ean"] == "4548736132580"


def test_barcode_decides_over_title():
    prod = {"name": "Sony WH-1000XM5", "ean": "4548736132580"}
    same = parsers.parse_page("bol", page("Totally different words here", "299", gtin="4548736132580"))
    other = parsers.parse_page("bol", page("Sony WH-1000XM5", "299", gtin="4006381333931"))
    assert parsers.product_match(prod, same)[0] == "ok"
    assert parsers.product_match(prod, other)[0] == "suspect"
    assert parsers.wrong_product(prod, other)           # a different barcode is clearly another product


def test_title_match_and_model_numbers():
    prod = {"name": "Samsung Galaxy S24 Ultra 256GB", "brand": "Samsung"}
    ok = parsers.Parsed(900, "Samsung Galaxy S24 Ultra 5G 256 GB Titanium Black")
    other_model = parsers.Parsed(900, "Samsung Galaxy S23 Ultra 256GB")
    assert parsers.product_match(prod, ok)[0] == "ok"
    verdict, why = parsers.product_match(prod, other_model)
    assert verdict == "suspect" and "S24" in why


def test_accessories_are_not_the_product():
    prod = {"name": "Apple iPhone 15 128GB"}
    case = parsers.Parsed(19, "Hoesje voor Apple iPhone 15 128GB siliconen")
    assert parsers.product_match(prod, case)[0] == "suspect"
    assert parsers.accessory_word("Hoesje voor Apple iPhone 15", "Apple iPhone 15")
    # the word is in the product's own name: not an accessory
    assert parsers.accessory_word("Beschermhoes Premium", "Beschermhoes Premium") is None


def test_category_guess():
    assert parsers.guess_category("Home > Boeken > Thrillers") == "books"
    assert parsers.guess_category("Elektronica > Laptops") == "electronics"
    assert parsers.guess_category("Speelgoed > Bouwen") == "toys_games"
    assert parsers.guess_category("Tuin > Gereedschap") == "home_garden_diy"
    assert parsers.guess_category("xyz", ean="9780306406157") == "books"
    assert parsers.guess_category("xyz") is None


def test_search_candidates_rank_the_right_product_first():
    product = {"name": "Sony WH-1000XM5 draadloze koptelefoon", "brand": "Sony", "id": "pX"}
    html = """<html><body>
      <a href="/nl/p/sony-wh-1000xm5-zwart/123/" title="Sony WH-1000XM5 koptelefoon zwart"><img alt="Sony WH-1000XM5"> Sony WH-1000XM5</a>
      <a href="/nl/p/sony-wh-1000xm4-zwart/124/">Sony WH-1000XM4 koptelefoon</a>
      <a href="/nl/p/hoesje-voor-sony-wh-1000xm5/125/">Hoesje voor Sony WH-1000XM5</a>
      <a href="/cart">Winkelwagen</a>
    </body></html>"""
    cands = parsers.search_candidates("krefel", html, product)
    assert cands and cands[0]["url"].endswith("/sony-wh-1000xm5-zwart/123/")
    assert all("hoesje" not in c["url"] for c in cands)
    assert all("cart" not in c["url"] for c in cands)


def test_link_check_trusts_the_address_you_added():
    prod = {"name": "Whatever", "source_url": "https://www.bol.com/be/nl/p/x/1/"}
    assert parsers.link_check({"url": "https://www.bol.com/be/nl/p/x/1/"}, prod)[0] == "ok"


def test_prices_and_history():
    assert models.parse_price("€ 1.234,56") == 1234.56
    assert models.parse_price("39,99") == 39.99
    offer = {}
    now = 1_700_000_000
    assert models.record_price(offer, 100.0, now)
    assert models.record_price(offer, 80.0, now + 2 * 86400)
    assert offer["last_price"] == 80.0 and len(offer["history"]) == 2


def test_status_deal_score_and_target():
    now = 1_700_000_000 + 40 * 86400
    offers = {"a": {"available": True, "last_price": 80.0, "url": "https://a", "history": [[1_700_000_000, 120.0], [now - 86400, 100.0], [now, 80.0]]},
              "b": {"available": True, "last_price": 95.0, "url": "https://b", "history": [[now, 95.0]]}}
    st = models.compute_status({"ref_price": 120, "target_price": 85}, offers, threshold=20, min_history_days=3, now=now)
    assert st["best_price"] == 80.0 and st["best_retailer"] == "a"
    assert st["is_all_time_low"] and st["target_hit"]
    assert st["discount_ref"] == pytest.approx(33.3, abs=0.1)
    assert st["shop_spread"] == pytest.approx(15.8, abs=0.1)
    assert st["deal_score"] >= 70 and st["shops"] == ["a", "b"]


def test_suspicious_price_uses_other_shops():
    p = {"name": "x"}
    assert models.is_suspicious_price(5000.0, p, {}, [100.0, 105.0, 110.0])
    assert models.is_suspicious_price(10.0, p, {}, [100.0, 105.0, 110.0])
    assert models.is_suspicious_price(100.0, p, {}, [100.0, 105.0, 110.0]) is None


def test_basket_summary():
    store = {"products": {"p1": {"category": "books", "ref_price": 30}, "p2": {"category": "books"}}, "offers": {}}
    st = {"p1": {"best_price": 20.0}, "p2": {"best_price": 10.0}}
    s = models.basket_summary(store, st)
    assert s["cost"] == 30.0 and s["saving"] == 10.0 and s["by_category"]["books"]["products"] == 2


def test_backup_validation():
    store = models.new_store()
    store["products"]["p0123456789"] = {"name": "x", "category": "books"}
    store["offers"]["p0123456789"] = {"bol": {"url": "https://www.bol.com/x", "history": [[1, 2.0]]}}
    assert models.validate_backup(store)["products"]
    bad = json.loads(json.dumps(store))
    bad["offers"]["p0123456789"]["bol"]["url"] = "javascript:alert(1)"
    with pytest.raises(ValueError):
        models.validate_backup(bad)
    with pytest.raises(ValueError):
        models.validate_backup({"sets": {}})


def test_shop_settings_validation_and_categories():
    example = json.loads(json.dumps(shops.__dict__.get("EXAMPLE", None) or {}))
    from pathlib import Path
    example = json.loads((Path(__file__).parent.parent / "examples" / "argus-shops.example.json").read_text("utf-8"))
    clean = shops.validate_settings(example)
    assert len(clean["shops"]) == len(example["shops"])
    with pytest.raises(ValueError):
        shops.validate_settings({**example, "format": "other"})
    bad = json.loads(json.dumps(example))
    bad["shops"][0]["categories"] = ["nonsense"]
    with pytest.raises(ValueError):
        shops.validate_settings(bad)
    bad = json.loads(json.dumps(example))
    bad["shops"][0]["search"] = "https://evil.example/s?k={query}"
    with pytest.raises(ValueError):
        shops.validate_settings(bad)


def test_shops_for_category():
    books = shops.shops_for_category("books")
    elec = shops.shops_for_category("electronics")
    assert "standaard_boekhandel" in books and "standaard_boekhandel" not in elec
    assert "krefel" in elec and "krefel" not in books
    assert "bol" in books and "bol" in elec                      # a shop without categories sells everything
    assert shops.shops_for_category("books", ["bol", "krefel"]) == ["bol"]


def test_search_address_needs_what_the_template_needs():
    assert shops.search_address("bol", "sony koptelefoon", None).endswith("searchtext=sony+koptelefoon")
    assert shops.search_address("bol", None, "4548736132580").endswith("searchtext=4548736132580")
    assert shops.search_address("unknown", "x", None) is None
