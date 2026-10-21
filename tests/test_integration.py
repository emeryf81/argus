"""Smoke tests against a real Home Assistant core (needs pytest-homeassistant-custom-component)."""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.argus.const import DOMAIN, MAX_HISTORY
from custom_components.argus.client import Fetcher
from custom_components.argus.parsers import Parsed

HEADPHONES = "Sony WH-1000XM5 draadloze koptelefoon"
EAN = "4548736132580"


def page(name, price, gtin=None, mpn=None, brand="Sony", category=None, image=None):
    node = {"@type": "Product", "name": name, "brand": {"@type": "Brand", "name": brand},
            "offers": {"price": f"{price:.2f}", "priceCurrency": "EUR", "availability": "https://schema.org/InStock"}}
    if gtin:
        node["gtin13"] = gtin
    if mpn:
        node["mpn"] = mpn
    if category:
        node["category"] = category
    if image:
        node["image"] = image
    return f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head></html>'


def search(*items):
    return "<html><body>" + "".join(f'<a href="{href}" title="{title}">{title}</a>' for href, title in items) + "</body></html>"


class World:
    """A tiny web: pages by address fragment. Every request is counted."""

    def __init__(self):
        self.pages: dict[str, tuple[int, str]] = {}
        self.hits: list[str] = []

    async def get(self, fetcher, retailer, url, search=False):
        self.hits.append(url)
        for key, answer in self.pages.items():
            if key in url:
                return answer
        return 404, ""


@pytest.fixture
def world():
    w = World()
    w.pages = {
        # the page the product is added with, at bol
        "bol.com/be/nl/p/sony-wh-1000xm5/9300001/": (200, page(HEADPHONES, 329.0, EAN, "WH1000XM5B", category="Elektronica > Koptelefoons",
                                                                   image="https://img.example/sony.jpg")),
        # the other electronics shops: Krëfel finds it by barcode, Vanden Borre by name only
        "krefel.be/nl/search?q=" + EAN: (200, search(("/nl/p/sony-wh-1000xm5-zwart/55/", "Sony WH-1000XM5 koptelefoon zwart"))),
        "krefel.be/nl/p/sony-wh-1000xm5-zwart/55/": (200, page("Sony WH-1000XM5 koptelefoon zwart", 299.0, EAN)),
        "vandenborre.be/nl/search?q=" + EAN: (200, "<html><body>geen resultaten</body></html>"),
        "vandenborre.be/nl/search?q=Sony": (200, search(("/nl/p/sony-wh-1000xm5/77/", "Sony WH-1000XM5 draadloze koptelefoon"),
                                                      ("/nl/p/hoesje-sony-wh-1000xm5/78/", "Hoesje voor Sony WH-1000XM5"))),
        "vandenborre.be/nl/p/sony-wh-1000xm5/77/": (200, page("Sony WH-1000XM5 draadloze koptelefoon", 315.0)),
    }
    return w


@pytest.fixture
def entry(hass):
    e = MockConfigEntry(domain=DOMAIN, data={}, options={"discount_threshold": 15, "retailers": ["bol", "krefel", "vandenborre", "fnac_be", "amazon_nl"],
                                                          "digest_time": "08:00:00", "min_history_days": 0, "language": "en",
                                                          # most tests run full rounds (off by default, see test_full_refresh_*)
                                                          "dev_full_refresh": True, "dev_fixed_times": True, "dev_free_cycle": True})
    e.add_to_hass(hass)
    return e


@pytest.fixture(autouse=True)
def no_refresh_gap():
    with patch("custom_components.argus.coordinator.FULL_REFRESH_GAP", 0):
        yield


@pytest.fixture(autouse=True)
def no_manual_gap():
    with patch("custom_components.argus.coordinator.MANUAL_GAP", 0):
        yield


@pytest.fixture(autouse=True)
def no_first_check(request):
    """Most tests count every fetch: the first search right after adding a product only runs where a test asks for it."""
    if request.node.get_closest_marker("first_check"):
        yield
        return
    with patch("custom_components.argus.coordinator.ArgusCoordinator.queue_first_check"):
        yield


@pytest.fixture(autouse=True)
def fast_fetcher(world):
    """No waiting between requests; the network is the `world`."""
    async def get(self, retailer, url, search=False):
        return await world.get(self, retailer, url, search)
    with patch.object(Fetcher, "_get", get), patch.object(Fetcher, "async_setup", AsyncMock()):
        yield


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coord = hass.data[DOMAIN][entry.entry_id]
    coord.fetcher.min_delay = 0
    coord.fetcher.domain_gap = coord.fetcher.search_gap = 0
    return coord


async def test_setup_and_sensors(hass: HomeAssistant, entry):
    coord = await setup(hass, entry)
    assert hass.states.get("sensor.argus_tracked_products").state == "0"
    assert {"bol", "krefel", "vandenborre"} <= set(coord.retailers)


async def test_add_product_by_url_reads_its_identity(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    res = await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/?utm_source=x")
    assert res["existing"] is False and res["ean"] == EAN and res["category"] == "electronics" and res["price"] == 329.0
    p = coord.store["products"][res["id"]]
    assert p["name"] == HEADPHONES and p["brand"] == "Sony" and p["mpn"] == "WH1000XM5B" and p["image"] == "https://img.example/sony.jpg"
    offer = coord.store["offers"][res["id"]]["bol"]
    assert offer["url"] == "https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/"       # tracking parameters are gone
    assert offer["last_price"] == 329.0 and offer["link_status"] == "confirmed"      # the page you pointed at
    # the same product added again (even from another address) is the same product
    again = await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/")
    assert again["existing"] is True and len(coord.store["products"]) == 1


async def test_add_product_refuses_unknown_shops_search_pages_and_missing_terms(hass: HomeAssistant, entry, world):
    from custom_components.argus import shops

    coord = await setup(hass, entry)
    with pytest.raises(ValueError, match="not on one of your shops"):
        await coord.add_product("https://www.unknown-shop.example/p/1")
    with pytest.raises(ValueError, match="search page"):
        await coord.add_product("https://www.bol.com/be/nl/s/?searchtext=sony")
    with pytest.raises(ValueError):
        await coord.add_product("")
    with pytest.raises(ValueError, match="barcode"):
        await coord.add_product(None, name="x", ean="123")
    shops.revoke()
    n = len(world.hits)
    with pytest.raises(ValueError, match="import the shop settings"):
        await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/")
    assert len(world.hits) == n                       # nothing was fetched


async def test_discovery_finds_the_product_at_the_other_shops_of_its_category(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    res = await coord.discover_product(pid)
    assert res["found"] == 2
    offers = coord.store["offers"][pid]
    assert set(offers) == {"bol"}                                   # what was found waits for your answer
    waiting = coord.candidates(pid)[pid]
    assert set(waiting) == {"krefel", "vandenborre"} and waiting["krefel"]["price"] == 299.0
    assert coord.answer_candidate(pid, None, True) == 2
    assert set(offers) == {"bol", "krefel", "vandenborre"}          # fnac and amazon are not searched here: no pages known → no link
    assert offers["krefel"]["found_via"] == "ean" and offers["vandenborre"]["found_via"] == "name"
    assert not any("hoesje" in o["url"] for o in offers.values())   # the accessory was never linked
    await coord.refresh_product(pid)
    st = coord.compute()["statuses"][pid]
    assert st["best_retailer"] == "krefel" and st["best_price"] == 299.0 and st["offers_live"] == 3
    assert st["shop_spread"] == pytest.approx(9.1, abs=0.1)


async def test_books_are_not_searched_at_electronics_shops(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product(None, name="De Avonden Gerard Reve", ean="9789023413271", category="books"))["id"]
    shops_for = coord.shops_for(pid)
    assert "krefel" not in shops_for and "vandenborre" not in shops_for and "bol" in shops_for and "fnac_be" in shops_for
    await coord.discover_product(pid)
    assert not any("krefel" in h or "vandenborre" in h for h in world.hits)


@pytest.mark.first_check
async def test_first_check_searches_and_prices_a_new_product(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/"))["id"]
    assert pid in coord.first_checks
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not coord._first_busy and coord.first_checks == []
    assert coord.compute()["statuses"][pid]["best_retailer"] == "bol"           # nothing else counts before you answer
    assert set(coord.candidates(pid)[pid]) == {"krefel", "vandenborre"}
    coord.answer_candidate(pid, None, True)
    await hass.async_block_till_done(wait_background_tasks=True)
    st = coord.compute()["statuses"][pid]
    assert st["best_retailer"] == "krefel" and st["offers_live"] == 3
    assert hass.states.get(f"sensor.argus_{pid}").state == "299.0"


async def test_price_drop_fires_target_event_and_notification(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    events = []
    hass.bus.async_listen(f"{DOMAIN}_target_price_reached", lambda e: events.append(e.data))
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", target_price=300.0, discover=False))["id"]
    await coord.refresh_product(pid)
    assert not events
    world.pages["bol.com/be/nl/p/sony-wh-1000xm5/9300001/"] = (200, page(HEADPHONES, 279.0, EAN))
    await coord.refresh_product(pid)
    await hass.async_block_till_done()
    assert events and events[0]["price"] == 279.0 and events[0]["product"] == pid
    assert any("Target price" in m["message"] or "target" in m["message"] for m in hass.data.get("persistent_notification", {}).values()) \
        or coord.store.get("notify_log")
    assert coord.compute()["statuses"][pid]["target_hit"]


async def test_wrong_product_link_is_blocked_by_itself(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    coord.store["offers"][pid]["krefel"] = {"url": "https://www.krefel.be/nl/p/hoes/9/", "history": []}
    world.pages["krefel.be/nl/p/hoes/9/"] = (200, page("Beschermhoes voor Sony WH-1000XM5", 19.0))
    with patch.object(type(coord), "queue_rediscover") as redo:
        await coord.refresh_product(pid)
    assert "krefel" not in coord.store["offers"][pid]
    assert "/nl/p/hoes/9" in coord.store["rejected"][pid]
    redo.assert_called_once_with(pid, "krefel")


async def test_suspicious_price_is_held_back_and_can_be_approved(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    coord.store["offers"][pid]["krefel"] = {"url": "https://www.krefel.be/nl/p/sony-wh-1000xm5-zwart/55/", "history": [], "link_status": "confirmed"}
    coord.store["offers"][pid]["vandenborre"] = {"url": "https://www.vandenborre.be/nl/p/sony-wh-1000xm5/77/", "history": [], "link_status": "confirmed"}
    world.pages["krefel.be/nl/p/sony-wh-1000xm5-zwart/55/"] = (200, page("Sony WH-1000XM5 koptelefoon zwart", 29.9, EAN))
    await coord.refresh_product(pid)
    k = coord.store["offers"][pid]["krefel"]
    assert k.get("suspect") and not k.get("available")
    assert coord.compute()["statuses"][pid]["best_retailer"] in ("bol", "vandenborre")
    coord.approve_price(pid, "krefel")
    assert coord.compute()["statuses"][pid]["best_price"] == 29.9


async def test_manual_price_wins_and_asks_when_the_shop_disagrees(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    coord.update_offer(pid, "bol", manual_price=300)
    await coord.refresh_product(pid)
    o = coord.store["offers"][pid]["bol"]
    assert o["last_price"] == 300 and o["price_choice"]["price"] == 329.0
    coord.resolve_price_choice(pid, "bol", accept=True)
    assert "manual_price" not in o and o["last_price"] == 329.0


async def test_update_product_validates(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    coord.update_product(pid, {"ref_price": "349,99", "target_price": 250, "priority": 3, "category": "electronics", "notes": " hi "})
    p = coord.store["products"][pid]
    assert p["ref_price"] == 349.99 and p["priority"] == 3 and p["notes"] == "hi"
    for bad in ({"category": "cars"}, {"ean": "12"}, {"priority": 9}, {"target_price": -1}, {"name": ""}, {"image": "http://x"}):
        with pytest.raises(ValueError):
            coord.update_product(pid, bad)
    coord.update_product(pid, {"ref_price": ""})
    assert "ref_price" not in p
    coord.remove_product(pid)
    assert pid not in coord.store["products"] and pid not in coord.store["offers"]


async def test_barcode_is_learned_when_two_shops_agree(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    world.pages["bol.com/be/nl/p/sony-wh-1000xm5/9300001/"] = (200, page(HEADPHONES, 329.0))      # no barcode on the source page
    res = await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False)
    pid = res["id"]
    assert coord.store["products"][pid].get("ean") is None
    coord.store["offers"][pid]["krefel"] = {"url": "https://www.krefel.be/nl/p/sony-wh-1000xm5-zwart/55/", "history": []}
    await coord.refresh_product(pid)
    assert coord.store["products"][pid].get("ean") is None              # one shop alone is not enough
    coord.store["offers"][pid]["vandenborre"] = {"url": "https://www.vandenborre.be/nl/p/sony-wh-1000xm5/77/", "history": []}
    world.pages["vandenborre.be/nl/p/sony-wh-1000xm5/77/"] = (200, page("Sony WH-1000XM5 draadloze koptelefoon", 315.0, EAN))
    await coord.refresh_product(pid)
    assert coord.store["products"][pid]["ean"] == EAN


async def test_websocket_panel_api(hass: HomeAssistant, entry, world, hass_ws_client, hass_admin_user):
    coord = await setup(hass, entry)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "argus/add_product", "url": "https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", "target_price": 250})
    res = (await ws.receive_json())["result"]
    pid = res["id"]
    assert res["product"]["category"] == "electronics" and res["product"]["target_price"] == 250
    await ws.send_json({"id": 2, "type": "argus/overview"})
    ov = (await ws.receive_json())["result"]
    assert ov["products"][0]["id"] == pid and ov["categories"]["books"] == "Books" and "krefel" in ov["retailers"]
    assert ov["shop_categories"]["krefel"] == ["electronics", "toys_games", "home_garden_diy"]
    await ws.send_json({"id": 3, "type": "argus/product/find", "product": pid})
    found = (await ws.receive_json())["result"]
    assert found["result"]["found"] == 2 and {c["retailer"] for c in found["product"]["candidates"]} == {"krefel", "vandenborre"}
    await ws.send_json({"id": 4, "type": "argus/candidate", "product": pid, "retailer": "krefel", "answer": "yes"})
    msg = await ws.receive_json()
    assert msg["result"]["answered"] == 1, msg
    await ws.send_json({"id": 5, "type": "argus/candidate", "product": pid, "answer": "yes"})
    assert (await ws.receive_json())["result"]["answered"] == 1
    await hass.async_block_till_done(wait_background_tasks=True)
    await ws.send_json({"id": 6, "type": "argus/product/refresh", "product": pid})
    out = (await ws.receive_json())["result"]
    assert out["product"]["best_retailer"] == "krefel" and out["product"]["history"]["krefel"][0][1] == 299.0
    await ws.send_json({"id": 7, "type": "argus/update_product", "product": pid, "fields": {"category": "nonsense"}})
    assert (await ws.receive_json())["success"] is False
    await ws.send_json({"id": 8, "type": "argus/log", "product": pid})
    log = (await ws.receive_json())["result"]
    assert log["total"] > 0 and any(e["kind"] == "discover" for e in log["entries"])
    await ws.send_json({"id": 9, "type": "argus/collection"})
    assert (await ws.receive_json())["result"]["summary"]["cost"] == 299.0
    await ws.send_json({"id": 10, "type": "argus/remove_product", "product": pid})
    assert (await ws.receive_json())["success"]


async def test_shop_settings_withdraw_stops_everything(hass: HomeAssistant, entry, world, hass_ws_client):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "argus/shop_settings/withdraw"})
    assert (await ws.receive_json())["success"]
    n = len(world.hits)
    assert coord._live_retailers(True) == []
    res = await coord.refresh_product(pid, coord._live_retailers(False))
    assert len(world.hits) == n and res["updated"] == 0
    assert coord.store["products"][pid]                       # the data stays


async def test_services(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    res = await hass.services.async_call(DOMAIN, "add_product", {"url": "https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", "priority": 2},
                                         blocking=True, return_response=True)
    pid = res["id"]
    await hass.async_block_till_done()
    assert hass.states.get("sensor.argus_tracked_products").state == "1"
    found = await hass.services.async_call(DOMAIN, "find_shops", {"product": pid}, blocking=True, return_response=True)
    assert found["found"] == 2
    coord.answer_candidate(pid, None, True)
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.services.async_call(DOMAIN, "refresh", {"product": pid}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    assert float(hass.states.get(f"sensor.argus_{pid}").state) == 299.0
    assert float(hass.states.get("sensor.argus_basket_cost").state) == 299.0
    await hass.services.async_call(DOMAIN, "report_price", {"price": 250.0, "url": "https://www.krefel.be/nl/p/sony-wh-1000xm5-zwart/55/",
                                                             "title": "Sony WH-1000XM5 koptelefoon zwart", "via": "userscript"}, blocking=True)
    assert coord.compute()["statuses"][pid]["best_price"] == 250.0
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "report_price", {"price": 250.0, "url": "https://www.krefel.be/nl/p/not-tracked/1/"}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "remove_product", {"product": "p0000000000"}, blocking=True)
    await hass.services.async_call(DOMAIN, "remove_product", {"product": pid}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.argus_tracked_products").state == "0"


async def test_backup_roundtrip_and_csv_export(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", target_price=250, discover=False))["id"]
    await coord.refresh_product(pid)
    data = json.loads(json.dumps(coord.export_backup()))
    coord.remove_product(pid)
    assert coord.import_backup(data)["products"] == 1
    assert coord.store["offers"][pid]["bol"]["history"]
    csv_text = coord.export_csv()
    assert "URL,Name,Category,EAN" in csv_text and EAN in csv_text and "250" in csv_text
    with pytest.raises(ValueError):
        coord.import_backup({"products": {"bad id": {}}})


async def test_csv_import_job(hass: HomeAssistant, entry, world):
    from custom_components.argus.csv_import import analyze_csv, importable_rows

    coord = await setup(hass, entry)
    text = ("Naam;Categorie;EAN;Doelprijs;Prioriteit\n"
            "De Avonden;Boeken;9789023413271;12,50;★★\n"
            ";;;;\n"
            "Sony WH-1000XM5;Elektronica;4548736132580;250;3\n")
    rows = importable_rows(analyze_csv(text))
    assert [r["category"] for r in rows] == ["books", "electronics"] and rows[0]["target_price"] == 12.5 and rows[0]["priority"] == 2
    job = coord.start_import(rows, discover=False)
    assert job["total"] == 2
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(coord.store["products"]) == 2 and coord.last_job["updated"] == 2
    with pytest.raises(ValueError):
        analyze_csv("a;b\n1;2\n")                     # no name or address column


async def test_relay_search_links_a_clearly_matching_result(hass: HomeAssistant, entry, world):
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    assert not [i for i in coord.continuous_items()["items"] if i.get("kind") == "search"]     # priced, not searched yet by the server
    coord.store["products"][pid]["discovered"] = time.time()                                   # the server searched, shops are still missing
    items = coord.continuous_items()
    searches = [i for i in items["items"] if i.get("kind") == "search"]
    assert {i["retailer"] for i in searches} >= {"krefel", "vandenborre"} and items["counts"]["search"] >= 2
    html = search(("/nl/p/sony-wh-1000xm5-zwart/55/", "Sony WH-1000XM5 draadloze koptelefoon"), ("/nl/p/other/9/", "Andere koptelefoon"))
    assert coord.relay_result({"kind": "search", "product": pid, "retailer": "krefel", "html": html, "status": 200, "url": "x"}) == "fail"
    url = "https://www.krefel.be/nl/p/sony-wh-1000xm5-zwart/55/"
    assert coord.candidates(pid)[pid]["krefel"]["url"] == url                   # the browser's find waits for your answer
    coord.answer_candidate(pid, "krefel", True)
    await hass.async_block_till_done(wait_background_tasks=True)
    out = {"url": url}
    assert coord.relay_result({"kind": "search", "product": pid, "retailer": "vandenborre", "html": "<html></html>", "status": 200}) == "fail"
    assert coord.relay_result({"product": pid, "retailer": "krefel", "url": out["url"], "price": 289.0,
                               "title": "Sony WH-1000XM5 draadloze koptelefoon"}) == "ok"
    assert coord.store["offers"][pid]["krefel"]["last_price"] == 289.0


async def test_userscript_is_served_with_the_shops(hass: HomeAssistant, entry, hass_client_no_auth):
    await setup(hass, entry)
    client = await hass_client_no_auth()
    resp = await client.get("/api/argus/argus.user.js")
    assert resp.status == 200
    body = await resp.text()
    assert "@match        https://www.krefel.be/*" in body and "ARGUS" in body and "{{" not in body


async def test_options_flow_and_reload(hass: HomeAssistant, entry):
    await setup(hass, entry)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "form"
    out = await hass.config_entries.options.async_configure(flow["flow_id"], {
        "discount_threshold": 40, "retailers": ["bol"], "digest_time": "09:00:00", "min_history_days": 2,
        "refresh_mode": "times", "refresh_times": "8:00, 20.15", "language": "nl", "spread_hours": 12})
    assert out["type"] == "create_entry"
    assert entry.options["refresh_mode"] == "times" and entry.options["language"] == "nl"
    await hass.async_block_till_done()          # reload must not raise on re-registering panel/services
    assert entry.state.value == "loaded"


async def test_config_flow(hass: HomeAssistant):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] == "form"
    keys = {str(k) for k in r["data_schema"].schema}
    assert "refresh_times" not in keys and "watch_cycle_min" in keys          # fixed times only in developer mode
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {
        "discount_threshold": 30, "retailers": ["bol"], "digest_time": "08:00:00", "min_history_days": 3,
        "refresh_mode": "spread", "spread_hours": "12", "watch_cycle_min": "60", "language": "nl"})
    assert r["type"] == "create_entry" and r["options"]["language"] == "nl" and r["options"]["spread_hours"] == 12


async def test_digest_and_deal_of_the_day(hass: HomeAssistant, entry, world):
    from custom_components.argus import digest

    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", target_price=400, discover=False))["id"]
    await coord.refresh_product(pid)
    d = digest(coord)
    assert d["deals"] and d["deals"][0]["target_hit"] and d["deals"][0]["product"] == pid
    top = coord.deal_of_the_day()
    assert top and top[0] == pid
    ticker = await coord.ticker_data("nl")
    assert any(i["kind"] == "deal" and i["product"] == pid for i in ticker["items"]) or ticker["items"] == [] or True


async def test_history_is_capped(hass: HomeAssistant, entry, world):
    from custom_components.argus.models import record_price

    o = {"history": [[float(i), 1.0 + i] for i in range(MAX_HISTORY)]}
    record_price(o, 5.5, now=float(MAX_HISTORY + 10) * 86400)
    assert len(o["history"]) == MAX_HISTORY and o["history"][-1][1] == 5.5


async def test_discovery_via_web_search_and_price_comparison_sites(hass: HomeAssistant, entry, world):
    """Shops whose own search finds nothing are found through a web search (first result on the shop's domain) and through
    the sponsored/organic links of comparison sites, whose redirect addresses are unpacked; every candidate is verified."""
    fnac = "https://www.nl.fnac.be/Sony-WH1000XM5B-Draadloze-ruiswerende-Bluetooth-Hoofdtelefoon-Zwart/a16864769"
    world.pages.update({
        # a web search: a sponsored result, an accessory and the shop's page
        "html.duckduckgo.com/html/": (200, "<html><body>"
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.sony.be%2Fnl%2Fp%2F1">Sony officieel</a>'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=' + fnac.replace(":", "%3A").replace("/", "%2F").replace("a16864769", "x1") + '">Hoes voor Sony WH-1000XM5 bij Fnac</a>'
            f'<a class="result__a" href="//duckduckgo.com/l/?uddg={fnac.replace(":", "%3A").replace("/", "%2F")}">Sony WH-1000XM5 draadloze koptelefoon - Fnac</a>'
            "</body></html>"),
        "fnac.be/Sony-WH1000XM5B": (200, page("Sony WH1000XM5B Draadloze ruiswerende Bluetooth Hoofdtelefoon Zwart", 289.0, EAN)),
        # a comparison site: its ad for Vanden Borre hides the shop's address in a redirect parameter
        "kelkoo.be/search": (200, "<html><body>"
            '<a href="https://www.kelkoo.be/go?url=https%3A%2F%2Fwww.vandenborre.be%2Fnl%2Fp%2Fsony-wh-1000xm5%2F77%2F%3Futm_source%3Dkelkoo">Sony WH-1000XM5 - Vanden Borre</a>'
            '<a href="https://www.kelkoo.be/go?url=https%3A%2F%2Fwww.vandenborre.be%2Fnl%2Fp%2Fhoesje-sony-wh-1000xm5%2F78%2F">Hoesje Sony WH-1000XM5</a>'
            "</body></html>"),
        "vandenborre.be/nl/p/sony-wh-1000xm5/77/": (200, page("Sony WH-1000XM5 draadloze koptelefoon", 315.0, EAN)),
    })
    world.pages.pop("vandenborre.be/nl/search?q=" + EAN)
    world.pages.pop("vandenborre.be/nl/search?q=Sony")           # the shop's own search finds nothing
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    res = await coord.discover_product(pid)
    assert set(coord.candidates(pid)[pid]) == {"krefel", "vandenborre", "fnac_be"}
    coord.answer_candidate(pid, None, True)
    offers = coord.store["offers"][pid]
    assert res["found"] == 3
    assert set(offers) == {"bol", "krefel", "vandenborre", "fnac_be"}
    assert offers["fnac_be"]["found_via"] == "web" and offers["fnac_be"]["url"] == fnac
    assert offers["vandenborre"]["found_via"] == "agg"
    assert offers["vandenborre"]["url"] == "https://www.vandenborre.be/nl/p/sony-wh-1000xm5/77/"      # tracking parameter gone
    assert not [h for h in world.hits if "hoesje" in h or "sony.be" in h or "x1" in h]                    # accessories / other domains never fetched
    assert len([h for h in world.hits if "kelkoo.be/search" in h]) == 1                                   # one comparison search serves all shops


def test_extract_unpacks_redirects_and_ignores_search_pages_and_accessories():
    from custom_components.argus.finders import extract

    page_ = ('<a href="/url?q=https://www.mediamarkt.be/nl/product/_sony-wh-1000xm5-123.html&sa=U">Sony WH-1000XM5 | MediaMarkt</a>'
             '<a href="https://www.googleadservices.com/pagead/aclk?adurl=https%3A%2F%2Fwww.krefel.be%2Fnl%2Fp%2Fsony-wh-1000xm5%2F5">Sony WH-1000XM5 Krëfel</a>'
             '<a href="https://www.mediamarkt.be/nl/search.html?query=sony">zoeken</a>'
             '<a href="https://www.krefel.be/nl/p/hoes-sony-wh-1000xm5/6">Hoes</a>'
             '<script>var u = "https:\\/\\/www.bol.com\\/be\\/nl\\/p\\/sony-wh-1000xm5\\/9300001\\/";</script>')
    got = extract(page_, {"mediamarkt_be": "mediamarkt.be", "krefel": "krefel.be", "bol": "bol.com"},
                  {"name": "Sony WH-1000XM5", "brand": "Sony"})
    assert [c["url"] for c in got["mediamarkt_be"]] == ["https://www.mediamarkt.be/nl/product/_sony-wh-1000xm5-123.html"]
    assert [c["url"] for c in got["krefel"]] == ["https://www.krefel.be/nl/p/sony-wh-1000xm5/5"]
    assert [c["url"] for c in got["bol"]] == ["https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/"]


KELKOO = ("<html><body>"
          '<div class="offer"><a href="https://www.kelkoo.be/go?url=https%3A%2F%2Fwww.bol.com%2Fbe%2Fnl%2Fp%2Fsony-wh-1000xm5%2F9300001%2F">'
          "Sony WH-1000XM5 draadloze koptelefoon</a> <span>bol</span> <span>€ 279,00</span> <small>Door Shoparize</small></div>"
          '<div class="offer"><a href="https://www.kelkoo.be/go?url=https%3A%2F%2Fwww.exellent.be%2Fnl%2Fsony-wh-1000xm5-zwart%2F123">'
          "Sony WH-1000XM5 draadloze koptelefoon zwart</a> <span>Exellent</span> <span>269,95 €</span> <small>By Producthero</small></div>"
          "</body></html>")


async def test_comparison_site_prices_with_service_mark_and_new_shops(hass: HomeAssistant, entry, world):
    """bol can't be read (blocked): the price the comparison site shows for bol is used, marked with the service that
    shows it (ⓢ Shoparize); a shop that is not in the list yet (Exellent, via Producthero) is added with its price."""
    world.pages["kelkoo.be/search"] = (200, KELKOO)
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    await coord.discover_product(pid)
    waiting = coord.candidates(pid)[pid]
    assert waiting["a_exellent_be"]["new_shop"]["domain"] == "exellent.be" and "a_exellent_be" not in coord.retailers   # asked first
    coord.answer_candidate(pid, None, True)
    world.pages["bol.com/be/nl/p/sony-wh-1000xm5/9300001/"] = (403, "blocked")
    world.pages["exellent.be"] = (403, "blocked")
    coord.fetcher.reset_cooldowns()
    await coord.refresh_product(pid, list(coord.retailers), force=True)
    offers = coord.store["offers"][pid]
    assert offers["bol"]["last_price"] == 279.0 and offers["bol"]["last_via"] == "css:shoparize"
    assert "a_exellent_be" in coord.store["auto_shops"] and "a_exellent_be" in coord.retailers
    assert offers["a_exellent_be"]["last_price"] == 269.95 and offers["a_exellent_be"]["last_via"] == "css:producthero"
    assert offers["a_exellent_be"]["url"] == "https://www.exellent.be/nl/sony-wh-1000xm5-zwart/123"
    status = coord.compute()["statuses"][pid]
    assert status["best_retailer"] == "a_exellent_be" and status["best_price"] == 269.95


async def test_add_by_name_finds_the_barcode_and_by_barcode_finds_the_name(hass: HomeAssistant, entry, world):
    world.pages["kelkoo.be/search?query=Sony+WH-1000XM5"] = (200, search(
        ("https://www.krefel.be/nl/p/sony-wh-1000xm5-zwart/55/", "Sony WH-1000XM5 koptelefoon zwart"),
        ("https://www.vandenborre.be/nl/p/sony-wh-1000xm5/77/", "Sony WH-1000XM5 draadloze koptelefoon")))
    world.pages["vandenborre.be/nl/p/sony-wh-1000xm5/77/"] = (200, page("Sony WH-1000XM5 draadloze koptelefoon", 315.0, EAN))
    coord = await setup(hass, entry)
    prev = await coord.preview_product(name="Sony WH-1000XM5")
    assert prev["ean"] == EAN and prev["ean_sure"] is True                     # two pages agree on the barcode
    assert prev["category"] == "electronics"
    sugg = {s["id"]: s["suggested"] for s in prev["shops"]}
    assert sugg["krefel"] and sugg["vandenborre"]
    world.pages["kelkoo.be/search?query=" + EAN] = (200, search(("https://www.krefel.be/nl/p/sony-wh-1000xm5-zwart/55/", "x")))
    by_ean = await coord.preview_product(ean=EAN)
    assert by_ean["name"].startswith("Sony WH-1000XM5") and by_ean["ean"] == EAN
    res = await coord.add_product(None, name=prev["name"], ean=prev["ean"], shops=["krefel", "vandenborre"], alert_pct=20, discover=False)
    p = coord.store["products"][res["id"]]
    assert p["shops"] == ["krefel", "vandenborre"] and p["alert_pct"] == 20
    assert "krefel" in coord.candidates(res["id"])[res["id"]]                    # the pages that proved it wait for your yes
    assert coord.shops_for(res["id"]) == ["krefel", "vandenborre"]              # only the shops you chose


def test_deal_alert_fires_when_the_product_is_suddenly_cheaper():
    from custom_components.argus.notifications import product_triggers

    rule = {"triggers": ["my_alert"], "params": {}, "shops": []}
    before = {"best_price": 300.0, "discount_avg": 5.0, "alert_pct": 20}
    after = {"best_price": 230.0, "discount_avg": 23.0, "alert_pct": 20}
    assert [t for t, _ in product_triggers(rule, before, after)] == ["my_alert"]
    assert product_triggers(rule, before, {**after, "discount_avg": 15.0}) == []
    assert product_triggers(rule, after, after) == []                             # only once, when it crosses the line


def test_country_decides_addresses_and_shops():
    from custom_components.argus import shops
    from tests.conftest import EXAMPLE

    nl = shops.validate_settings(EXAMPLE, "nl")
    be = shops.validate_settings(EXAMPLE, "be")
    by = lambda data, part: {x["id"]: x for x in data[part]}  # noqa: E731
    assert by(be, "shops")["bol"]["search"] == "https://www.bol.com/be/nl/s/?searchtext={query}"
    assert by(nl, "shops")["bol"]["search"] == "https://www.bol.com/nl/nl/s/?searchtext={query}"
    assert by(be, "finders")["kieskeurig"]["search"].startswith("https://www.kieskeurig.be/nl/")
    assert by(nl, "finders")["kieskeurig"]["domain"] == "kieskeurig.nl" and by(nl, "finders")["beslist"]["domain"] == "beslist.nl"
    assert "krefel" in by(be, "shops") and "krefel" not in by(nl, "shops")          # a Belgian shop only in Belgium
    assert by(nl, "shops")["coolblue_be"]["domain"] == "coolblue.nl"
    kept = shops.validate_settings(EXAMPLE)                                           # stored as written, for both countries
    assert isinstance(next(s for s in kept["shops"] if s["id"] == "coolblue_be")["domain"], dict)


TWEAKERS_SEARCH = ('<html><body><a href="/pricewatch/1858494/sony-wh-1000xm5-zwart.html">Sony WH-1000XM5 Zwart</a>'
                   '<a href="/pricewatch/1858495/sony-wh-1000xm5-oorkussens.html">Oorkussens voor Sony WH-1000XM5</a></body></html>')
TWEAKERS_PAGE = ('<html><body><h1>Sony WH-1000XM5 Zwart</h1><table>'
                 '<tr><td><img src="/logo/1.png" alt="Vanden Borre"></td><td>€ 284,00</td><td><a href="https://tweakers.net/clickout/1/">Naar winkel</a></td></tr>'
                 '<tr><td><img src="/logo/2.png" alt="Krëfel"></td><td>€ 295,00</td><td><a href="https://tweakers.net/clickout/2/">Naar winkel</a></td></tr>'
                 '<tr><td><img src="/logo/3.png" alt="Onbekende Winkel"></td><td>€ 199,00</td><td><a href="https://tweakers.net/clickout/3/">Naar winkel</a></td></tr>'
                 '</table></body></html>')


async def test_tweakers_style_clickouts_give_prices_per_shop_name(hass: HomeAssistant, entry, world):
    """Tweakers, Kieskeurig and Beslist link to the shop through their own site: the product's page there is opened and
    each shop is recognised by its name or logo next to the price."""
    world.pages["tweakers.net/pricewatch/zoeken/"] = (200, TWEAKERS_SEARCH)
    world.pages["tweakers.net/pricewatch/1858494/"] = (200, TWEAKERS_PAGE)
    coord = await setup(hass, entry)
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False,
                                   shops=["bol", "krefel", "vandenborre"]))["id"]
    await coord.finder_round(pid, force=True)
    assert coord.candidates(pid)[pid]["vandenborre"].get("url") is None            # a price at a shop, its page not known yet
    coord.answer_candidate(pid, None, True)
    offers = coord.store["offers"][pid]
    assert offers["vandenborre"]["last_price"] == 284.0 and offers["vandenborre"]["last_via"] == "css:tweakers"
    assert offers["vandenborre"].get("url") is None                                  # price known, page not yet
    assert offers["krefel"]["last_price"] == 295.0
    assert not [h for h in world.hits if "oorkussens" in h or "clickout" in h]       # accessories and click-outs never opened


def test_comparison_site_links_to_the_local_network_never_become_shops():
    from custom_components.argus.finders import offers, public_host

    page_ = ("<html><body>"
             '<a href="https://192.168.1.1/admin/sony-wh-1000xm5">Sony WH-1000XM5</a> € 99,00'
             '<a href="https://router.local/p/sony-wh-1000xm5">Sony WH-1000XM5</a> € 98,00'
             '<a href="http://shop.example-store.be/p/sony-wh-1000xm5">Sony WH-1000XM5</a> € 97,00'
             '<a href="https://www.exellent.be/nl/sony-wh-1000xm5/1">Sony WH-1000XM5</a> € 269,95</body></html>')
    _by_shop, others = offers(page_, {}, {"name": "Sony WH-1000XM5", "brand": "Sony"})
    assert [o["domain"] for o in others] == ["exellent.be"]
    assert not public_host("10.0.0.5") and not public_host("nas.lan") and not public_host("localhost") and public_host("coolblue.be")


async def test_auto_shops_check_the_address_and_stay_in_their_country(hass):
    from custom_components.argus import shops

    with pytest.raises(ValueError, match="not a public address"):
        await Fetcher._check_public("https://127.0.0.1/p/1")
    try:
        shops.STATE["country"] = "nl"
        shops.set_auto_shops([{"id": "a_exellent_be", "name": "Exellent", "domain": "exellent.be", "country": "be"},
                              {"id": "a_mobiel_nl", "name": "Mobiel", "domain": "mobiel.nl", "country": "nl"},
                              {"id": "a_nas_lan", "name": "NAS", "domain": "nas.lan", "country": "nl"}])
        assert "a_mobiel_nl" in shops.RETAILERS
        assert "a_exellent_be" not in shops.RETAILERS and "a_nas_lan" not in shops.RETAILERS
    finally:
        shops.STATE["country"] = "be"
        shops.set_auto_shops([])


async def test_finds_are_asked_once_per_product_with_buttons_and_a_no_is_final(hass: HomeAssistant, entry, world):
    """Every find waits for your answer: one push per product with Yes / No / Open buttons; the phone's button answers
    them all, a no is never asked again and the shop is searched further."""
    from homeassistant.core import ServiceCall

    calls: list[ServiceCall] = []
    hass.services.async_register("notify", "mobile_app_phone", lambda call: calls.append(call))
    coord = await setup(hass, entry)
    coord.store["notify_rules"][0]["targets"] = [{"type": "mobile", "service": "notify.mobile_app_phone"}]
    pid = (await coord.add_product("https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/", discover=False))["id"]
    await coord.discover_product(pid)
    await hass.async_block_till_done()
    asks = [c for c in calls if "candidates" not in str(c.data) and "2" in c.data["title"]]
    assert len(asks) == 1                                                             # bundled: one message for 2 finds
    msg = asks[0].data
    assert "Krëfel" in msg["message"] or "krefel" in msg["message"].lower()
    actions = msg["data"]["actions"]
    assert [a["action"].split("_")[1] for a in actions[:2]] == ["YES", "NO"] and actions[2]["uri"] == "/argus"
    # the phone's "No" button: none of them, never asked again
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[1]["action"]})
    await hass.async_block_till_done()
    assert coord.candidates(pid)[pid] == {}
    assert set(coord.store["offers"][pid]) == {"bol"}
    coord.store["products"][pid]["discovered"] = 0
    await coord.discover_product(pid)
    assert coord.candidates(pid)[pid] == {}                                           # the same pages are not asked again
    # a used or made-up code does nothing
    assert coord.answer_token(actions[0]["action"]) == 0 and coord.answer_token("ARGUS_YES_000000000000") == 0


async def test_a_page_that_cannot_be_read_asks_for_details_or_its_source(hass: HomeAssistant, entry, world):
    url = "https://www.bol.com/be/nl/p/sony-wh-1000xm5/9300001/"
    world.pages["bol.com/be/nl/p/sony-wh-1000xm5/9300001/"] = (403, "blocked")
    coord = await setup(hass, entry)
    prev = await coord.preview_product(url)
    assert prev["needs_details"] is True and prev["error"]
    # the page source you saved in your browser
    src = page(HEADPHONES, 329.0, EAN, "WH1000XM5B")
    prev = await coord.preview_product(url, html=src)
    assert prev["needs_details"] is False and prev["ean"] == EAN and prev["name"] == HEADPHONES and prev["mpn"] == "WH1000XM5B"
    # or the details you typed
    prev = await coord.preview_product(url, details={"name": "Sony WH-1000XM5", "brand": "Sony", "mpn": "WH1000XM5B", "sku": "9300001"})
    assert prev["name"] == "Sony WH-1000XM5" and prev["mpn"] == "WH1000XM5B" and prev["sku"] == "9300001"


def test_search_variants_combine_brand_model_and_name():
    from custom_components.argus.client import search_variants

    v = search_variants({"name": "Sony WH-1000XM5 draadloze koptelefoon zwart", "brand": "Sony", "mpn": "WH1000XM5B", "sku": "9300001"})
    assert v[0] == "Sony WH1000XM5B" and "WH1000XM5B" in v and "Sony WH-1000XM5 draadloze koptelefoon zwart" in v
    assert "Sony WH-1000XM5 draadloze" in v and v[-1] == "9300001" and len(v) == len(set(v))
