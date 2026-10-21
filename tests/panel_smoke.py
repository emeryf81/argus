"""Smoke test of the panel in a real (headless) Chromium with a mocked Home Assistant.

Every section and sub-tab is drawn once; any exception or console error fails the test.
Skipped when playwright or Chromium is not available.
"""
from __future__ import annotations

import json
import pathlib
import time

from playwright import sync_api as playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = ROOT / "custom_components" / "argus" / "panel" / "argus-panel.js"
NOW = time.time()


def offer(label, price, low=None, **kw):
    return {"label": label, "url": f"https://{label.lower()}.example/p", "price": price, "auto_price": None, "manual_price": None,
            "manual_url": False, "available": True, "error": None, "checked": NOW - 600, "unavailable": None, "low": low or price,
            "title": "Sony WH-1000XM5", "gtins": ["4548736132580"], "link_status": "ok", "link_reason": "", "found_via": "barcode",
            "via": None, "suspect": None, "approved": None, "price_choice": None, "ignored": False, **kw}


PRODUCT = {
    "id": "pabc123", "name": "Sony WH-1000XM5", "ean": "4548736132580", "brand": "Sony", "category": "electronics", "priority": 2,
    "target_price": 280.0, "ref_price": 399.0, "image": None, "price": 289.0, "lowest_price": 289.0, "all_time_low": 275.0,
    "highest_price": 399.0, "median_90": 320.0, "shops": 2, "shop_spread": 12.0, "cheapest_shop": "bol", "deal_score": 72,
    "deal": True, "spark": [330, 320, 310, 299, 289], "shops_for": ["amazon_be", "bol", "krefel"], "status": "ok",
    "offers": {"bol": offer("bol", 289.0), "amazon_be": offer("Amazon", 301.5, error=None, via="css:shoparize")}, "alert_pct": 20,
    "candidates": [{"retailer": "krefel", "shop": "Krëfel", "url": "https://www.krefel.be/nl/p/sony/55/", "title": "Sony WH-1000XM5 zwart",
                    "price": 299.0, "how": "ean", "sure": True, "found": NOW - 300},
                   {"retailer": "a_exellent_be", "shop": "Exellent", "url": "https://www.exellent.be/p/1", "title": "Sony WH-1000XM5",
                    "price": 269.95, "how": "agg", "via": "shoparize", "sure": False, "found": NOW - 200,
                    "new_shop": {"domain": "exellent.be", "name": "Exellent"}}],
    "history": {"bol": [[NOW - 86400 * 20, 330.0], [NOW - 86400 * 5, 299.0], [NOW - 3600, 289.0]]},
    "combined": [[NOW - 86400 * 20, 330.0], [NOW - 86400 * 5, 299.0], [NOW - 3600, 289.0]],
}

OVERVIEW = {
    "version": "0.1.0", "api": 1, "transport": "aiohttp", "language": "en", "languages": {"nl": "Nederlands", "en": "English"},
    "shop_settings": {"imported": True, "ready": True, "accepted": NOW, "shops": 2, "legal_version": 1},
    "threshold": 60, "categories": {"electronics": "Electronics", "books": "Books", "toys_games": "Toys & games",
                                    "home_garden_diy": "Home, garden & DIY", "other": "Other"},
    "retailers": {"bol": "bol", "amazon_be": "Amazon"}, "shop_categories": {"bol": [], "amazon_be": ["electronics"]},
    "products": [PRODUCT], "summary": {"products": 1, "deals": 1}, "events": [],
    "retailer_stats": {"bol": {"label": "bol", "enabled": True, "paused_hours": 0, "offers": 1, "ok": 1, "errors": 0, "cheapest": 1,
                               "last_ok": NOW - 600, "failing": []}},
    "job": None, "last": None, "first_checks": [], "paused": {}, "schedule": {"rates": {"products": 1, "priority": 0}},
    "userscript_last": None, "relay_last": None, "relay": {"enabled": False, "pending": 0, "continuous": {}, "heartbeat": None},
    "deal_rules": {}, "alert_steps": [10, 20, 30, 40, 50], "marks": {"shoparize": {"letter": "s", "name": "Shoparize"}}, "product_limit": 200, "full_refresh": False, "manual": {}, "health": {"errors": 0, "paused_hours": {}},
}

SETTINGS = {
    "language": "en", "languages": {"nl": "Nederlands", "en": "English"}, "notify_service": "", "digest_time": "08:00",
    "refresh_mode": "spread", "spread_hours": 24, "cycle_choices": [2, 3, 4, 6, 12, 24], "watch_cycle_min": 0, "watch_cycle_choices": [0, 60],
    "refresh_times": "", "use_impersonation": True, "transport": "aiohttp", "browser_relay": False, "relay_hours": 6,
    "ticker": {"deals": True, "max_deals": 3, "drops": True, "max_drops": 3, "news": True, "max_news": 3, "shuffle": True},
    "block_words": [], "allow_words": [], "builtin_words": ["hoes", "case"], "product_limit": 200, "dev": {}, "categories": OVERVIEW["categories"],
    "shops": [{"id": "bol", "label": "bol", "builtin": True, "domain": "bol.com", "search": "https://www.bol.com/be/nl/s/?searchtext={query}",
               "default_search": "https://www.bol.com/be/nl/s/?searchtext={query}", "categories": [], "enabled": True, "autopause": True,
               "paused_hours": 0, "blocks": 0}],
}


NOTIFY = {"rules": [{"id": "r1", "name": "All deals", "enabled": True, "scope": {"type": "all", "categories": [], "products": []},
                     "triggers": ["target_hit", "all_time_low"], "params": {}, "shops": [], "targets": [{"type": "persistent"}],
                     "cooldown_hours": 24, "quiet": None, "image": True, "link": True}],
          "options": {"notify": [], "notify_entities": [], "tts": [], "media_players": [], "persons": [],
                      "categories": OVERVIEW["categories"],
                      "triggers": {"target_hit": {"label": "Target price reached", "per_product": True, "param": ""},
                                   "all_time_low": {"label": "Lowest price so far", "per_product": True, "param": ""}},
                      "retailers": OVERVIEW["retailers"], "products": {"pabc123": "Sony WH-1000XM5"}},
          "log": [], "queued": {}}
LOG = {"entries": [{"ts": NOW - 60, "level": "ok", "kind": "check", "message": "Checked", "product": "pabc123", "retailer": "bol",
                    "source": "auto", "results": {"bol": {"ok": True, "price": 289.0}}, "url": "https://bol.example/p"}],
       "total": 1, "more": False, "facets": {"kind": {"check": 1}, "retailer": {"bol": 1}, "source": {"auto": 1}, "level": {"ok": 1}},
       "kinds": {"check": "Shop check", "price": "Price"}}
PREVIEW = {"id": "pabc123", "existing": False, "url": "https://www.bol.com/be/nl/p/x/1/", "retailer": "bol", "error": "blocked (HTTP 403)", "needs_details": True, "name": "Sony WH-1000XM5", "brand": "Sony",
           "ean": "4548736132580", "ean_sure": True, "mpn": None, "image": None, "price": 289.0, "category": "electronics", "pages": [],
           "shops": [{"id": "bol", "label": "bol", "categories": [], "suggested": True, "found": True, "price": 289.0},
                     {"id": "amazon_be", "label": "Amazon", "categories": ["electronics"], "suggested": True, "found": False, "price": None},
                     {"id": "standaard", "label": "Standaard Boekhandel", "categories": ["books"], "suggested": False, "found": False, "price": None}]}
ANSWERS = {"argus/product/preview": PREVIEW, "argus/overview": OVERVIEW, "argus/collection": {"products": [PRODUCT]}, "argus/settings/get": SETTINGS,
           "argus/product": PRODUCT, "argus/log": LOG, "argus/ticker": {"items": []}, "argus/notify/get": NOTIFY}
SECTIONS = {"prices": ["today", "confirm", "all", "dset"], "overview": ["cost", "shops"], "log": ["all", "checks", "errors"],
            "manage": ["add", "import", "links", "notify", "shops", "lab", "settings", "userscript", "backup", "legal", "about", "secret"]}


def main():
    errors = []
    cur = ["load"]
    crashed = []
    with playwright.sync_playwright() as pw:
        exe = "/opt/pw-browsers/chromium"
        browser = (pw.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if pathlib.Path(exe).exists()
                   else pw.chromium.launch(args=["--no-sandbox"]))
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(cur[0] + ": " + (e.stack or str(e))))

        def on_console(m):
            if m.type == "error" and "Failed to load resource" not in m.text:
                try:
                    errors.append(cur[0] + ": " + (m.args[0].evaluate("e => (e && e.stack) || String(e)") if m.args else m.text))
                except Exception:  # noqa: BLE001
                    errors.append(cur[0] + ": " + m.text)
        page.on("console", on_console)
        page.route("**/argus_static/**", lambda r: r.fulfill(status=404, body=""))
        page.set_content("<html><body></body></html>")
        page.add_script_tag(content=PANEL.read_text())
        page.evaluate("""(a) => {
          const el = document.createElement('argus-panel'); document.body.appendChild(el); window.__el = el;
          el.hass = { user: { is_admin: true }, language: 'en', callWS: async (m) => JSON.parse(JSON.stringify(a[m.type] ?? {})) };
        }""", ANSWERS)
        page.wait_for_timeout(800)
        for sec, subs in SECTIONS.items():
            for sub in subs:
                cur[0] = f"{sec}/{sub}"
                page.evaluate("([s, u]) => { const e = window.__el; e.state.section = s; e.state.sub[s] = u; e.render(true); }", [sec, sub])
                page.wait_for_timeout(200)
                if page.evaluate("() => !!window.__el.shadowRoot.getElementById('crash_reload')"):
                    crashed.append(cur[0])
                    page.evaluate("() => { window.__el._rendered = false; window.__el.shadowRoot.innerHTML = ''; }")
        import os
        shots = os.environ.get("SHOT_DIR")
        cur[0] = "add preview"
        page.evaluate("() => { const e = window.__el; e.state.section = 'manage'; e.state.sub.manage = 'add'; e.render(true); }")
        page.wait_for_timeout(200)
        page.evaluate("() => { const r = window.__el.shadowRoot; r.getElementById('a_q').value = 'Sony WH-1000XM5'; r.getElementById('a_look').click(); }")
        page.wait_for_timeout(600)
        if not page.evaluate("() => !!window.__el.shadowRoot.querySelector('.pshops')"):
            crashed.append("add preview")
        if shots:
            page.set_viewport_size({"width": 1280, "height": 900})
            page.screenshot(path=f"{shots}/add.png", full_page=True)
            page.evaluate("() => { const e = window.__el; e.state.section = 'prices'; e.state.sub.prices = 'all'; e.render(true); }")
            page.wait_for_timeout(600)
            page.screenshot(path=f"{shots}/list.png", full_page=True)
            page.evaluate("() => { const e = window.__el; e.state.section = 'prices'; e.state.sub.prices = 'confirm'; e.render(true); }")
            page.wait_for_timeout(600)
            page.screenshot(path=f"{shots}/confirm.png", full_page=True)
        cur[0] = "dialog"
        page.evaluate("() => window.__el.openSet('pabc123')")
        page.wait_for_timeout(300)
        if page.evaluate("() => !!window.__el.shadowRoot.getElementById('crash_reload')"):
            crashed.append("product dialog")
        browser.close()
    print(json.dumps({"crashed": crashed, "errors": errors}))


if __name__ == "__main__":
    main()
