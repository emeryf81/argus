<p align="center"><img src="images/banner.png" alt="ARGUS – Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden" width="100%"></p>

# ARGUS

**A**ltijd **R**ondkijken, **G**oedkoopste **U**itzoeken, **S**nel melden —
*always look around, pick the cheapest, report quickly.*

ARGUS watches the price of a product over several shops, keeps a price-history chart and alerts you when the price drops
below your target or below the lowest point of the past months. Like the giant of Greek myth with a hundred eyes, never
all of them asleep at once. It is a custom integration for [Home Assistant](https://www.home-assistant.io/) (installable
through [HACS](https://hacs.xyz/)) and runs entirely on your own installation.

> 🇳🇱 **Nederlands** — ARGUS houdt de prijs van een product in het oog bij meerdere winkels, bewaart een grafiek van de
> prijsgeschiedenis en waarschuwt je zodra de prijs onder je streefprijs of onder het laagste punt van de afgelopen maanden
> zakt. De standaardtaal is Nederlands; er zijn ook Engels, Frans, Duits, Spaans, Chinees, Koreaans en Indonesisch.

## How it works

1. **Type what you want to watch** — the address of a product page (bol.com, Amazon, Fnac…), a **name**
   (`Sony WH-1000XM5`) or a **barcode** (`4548736132580`). ARGUS looks it up first: from a name it finds the barcode
   (trusted when two pages agree), from a barcode the name, brand and picture. From then on everything is searched by
   barcode, which is the same at every shop.
2. ARGUS **suggests which of your shops to watch for this kind of product** — electronics at Amazon, Krëfel, Fnac,
   Vanden Borre, MediaMarkt…; books at Fnac, Standaard Boekhandel, bol…; it never looks for headphones at a bookshop. You
   tick or untick, and set a **maximum price** and/or a **deal alert** (“tell me when it is suddenly 10 / 20 / 30 / 40 /
   50 % cheaper than usual”).
3. It finds the product's page at each of those shops (see below). Every candidate is **verified** before it is linked:
   the barcode on the page must match, otherwise the title must cover the product's name and model number, and it must
   not be an accessory (case, cable, spare part…) or a far-too-cheap lookalike.
4. Every product is checked once per cycle at every shop, spread over the day so the shops are not hammered. Comparison
   sites are asked too (twice a day): their offers fill the gaps.
5. Your **watch list** shows per product where it is cheapest and for how much, every shop coloured from **green (cheap)
   to red (dear)**, your maximum price and your deal alert (light → bright green) — both editable right there. Plus a
   **deal score**, a **price-history chart**, a **ticker**, Home Assistant **sensors** and **notifications**.

### Prices from comparison services: ⓢ ⓟ ⓒ …

Shops advertise in Google Shopping, Bing Shopping and on comparison sites through *Comparison Shopping Services* such as
**Shoparize, Producthero, Channable**, Kelkoo, idealo… ARGUS reads those offers (sponsored ones included) and keeps, per
shop, the price they show and the service that shows it:

- **A shop ARGUS can't read itself** (blocked, captcha, JavaScript) still gets a price: the one the comparison service
  shows, marked with the service's letter in a circle — **ⓢ** Shoparize, **ⓟ** Producthero, **ⓒ** Channable,
  **ⓚ** Kelkoo, **ⓘ** idealo, **ⓖ** Google Shopping, **ⓜ** Bing Shopping… (prices from your own browser keep **ⓤ**).
  The shop's own page always wins as soon as it can be read; a comparison price older than 3 days is not used.
- **Shops you don't have yet** that sell the product (with a matching title or found by barcode) are **added to your list
  by themselves**, with their price ("new shop found via Producthero: …"). You can switch them off under *Manage →
  Settings → Shops*.

### Discovery methods

Several methods are combined, cheapest and surest first. **Every candidate is fetched from the shop and verified** (barcode,
model number, title, accessory words) before it is linked, and **prices are always read from the shop's own page** — a
finder only ever gives a suggestion.

| # | Method | What it does |
| --- | --- | --- |
| 1 | Shop search by barcode | `https://www.mediamarkt.be/nl/search.html?query=4548736132580`: the shop's own search for the EAN/ISBN; a redirect straight to the product page counts too |
| 2 | Price-comparison sites (*aggregators*) | one search per product (barcode, else name) at Google Shopping, Bing Shopping, Kelkoo…: **all** links to your shops are harvested, sponsored ads included (their redirect addresses — `adurl=`, `url=`, Bing's base64 `u=` — are unpacked to the shop's address) |
| 3 | Web search (*websearch*) | searches `Sony WH-1000XM5 fnac` at DuckDuckGo / Bing / Google and takes the first results on the shop's domain, e.g. `https://www.nl.fnac.be/Sony-WH1000XM5B-…/a16864769` |
| 4 | Shop search by name | the shop's own search by brand + name + model, ranked by title similarity |
| 5 | Browser search (userscript) | your own browser searches shops that block the server or render results with JavaScript |
| 6 | Manual | paste a link per shop in the product window; a manual link or price always wins |

Links to accessories (case, cable, spare part…), search pages, the shop's home page and other domains are dropped before
anything is fetched. A barcode confirmed by two shops is stored on the product, which makes later searches surer.

## Features

- **Product tracking** by URL, name, barcode or CSV import (up to 200 products), with categories, the shops to watch per
  product, priority (★–★★★), reference price, maximum price and a deal alert (10–50 % below the usual price).
- **Price history & deal score** — lowest ever, 90-day median, shop spread, target price; "price drop" and "lowest so far" badges.
- **Notifications** with a rule editor: scopes (all / priority / categories / products) × triggers (target reached, your deal alert,
  lowest price so far, discount, price below, price drop, deal score, new shop, back in stock, any change, daily digest, deal of
  the day, job finished, problems) × targets (mobile app, notify service, e-mail, persistent notification, TTS, event),
  quiet hours and cooldowns. Every notification also fires the event `argus_notification`.
- **Logbook & diagnosis** — everything the integration does, per shop and per product, with CSV export and a problem report.
- **Parser lab** — test how a shop page is read and why a price is (not) found.
- **Userscript (Tampermonkey)** — your own browser sends prices, performs searches shops block on servers, and adds the page
  you are viewing to ARGUS ("Add this page to ARGUS").
- **Backup / restore / CSV**, a **news feed**, and **8 languages** (Dutch default).
- **Sensors** — tracked products, products at lowest price so far, price drops, targets reached, basket cost and saving,
  offers with errors, best deal score, plus one price sensor per product.
- **Services** — `argus.add_product`, `remove_product`, `find_shops`, `refresh`, `verify_links`, `confirm_offer`,
  `remove_offer`, `set_offer`, `fix_offer`, `cancel_job`, `export_products`, `export_data`, `import_data`,
  `import_products`, `report_price`, `send_digest`.

## Installation

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/emeryf81/argus` as an **Integration**.
2. Install **ARGUS**, restart Home Assistant.
3. *Settings → Devices & services → Add integration → ARGUS*.
4. Open **ARGUS** in the sidebar.

### First start: the shop settings (legal gate)

ARGUS ships **without any list of shops** and contacts **no website** until you import a *shop settings* file and accept
the terms once. This is on purpose: which websites your Home Assistant contacts, and what that means legally, is your own
decision and responsibility.

- A ready-made **example** is in [`examples/argus-shops.example.json`](examples/argus-shops.example.json): 15 Belgian and
  Dutch shops (Amazon, bol, Krëfel, Vanden Borre, MediaMarkt, Coolblue, Fnac, Standaard Boekhandel, ToyChamp, Dreamland, Brico, Gamma, Hubo, IKEA) with their categories.
- Format `argus-shop-settings`, version 1: per shop an id, name, domain, `reader` (`marketplace` / `retail` / `generic`),
  `categories` and a `search` template containing `{query}` and/or `{ean}`; optionally `finders` (`kind`: `websearch` or
  `aggregator`, with `domain` and `search`). Finders are websites too: they fall under the same terms and can be switched
  off in *Manage → Settings → Finders*.
- In the panel: *Manage → Shops & jobs → Import shop settings*, read the terms, tick the box.
  You can withdraw at any time under *Manage → Legal*; from then on no shop is contacted.
- The search URL of every shop can be changed in *Manage → Settings*: search the shop for the word `ARGUSTEST`, paste the
  address and ARGUS turns it into a template.

> ⚠️ **The example search URLs (shops and finders) are best guesses and have not been verified against the live sites**, and shops change
> their pages. Use *Manage → Parser lab* to test a shop and adjust the search URL where needed. Search engines such as Google block
> servers quickly; ARGUS pauses a finder after a block and uses the others. Some shops block servers or
> render results with JavaScript; the userscript and manual links are the fallback.

## Politeness towards the shops

Per site at most one request every 30 s, a search at most every 2 minutes, automatic pauses after a block (1 → 3 → 6 → 12 →
24 h), same-site redirects only, a 25 MB cap per page, spread-out cycles (2–24 h). "Refresh everything at once" is
switched off by default. Please keep it that way.

## Development

```bash
python -m venv venv && . venv/bin/activate
pip install pytest pytest-asyncio aiohttp beautifulsoup4 voluptuous playwright
PYTHONPATH=. pytest tests -q          # parsers, fetcher, full integration scenarios on a fake web, i18n, panel smoke test
node --check custom_components/argus/panel/argus-panel.js
python scripts/i18n_extract.py        # lists untranslated strings per language
```

The panel is a dependency-free web component (`custom_components/argus/panel/argus-panel.js`); translations live in
`custom_components/argus/panel/i18n/<lang>.json` (English source text → translation). The brand kit is generated by
`scripts/brand.py`.

## Credits & support

Made by [Emery Frijters](https://github.com/emeryf81) from Belgium. ARGUS is independent software; the names of shops,
websites and products belong to their owners and this project is not affiliated with any of them.
Free software — if it saves you money, you can [buy me a coffee ☕](https://www.buymeacoffee.com/emeryf).
