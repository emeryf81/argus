"""Constants for the ARGUS integration."""
from __future__ import annotations

DOMAIN = "argus"
STORAGE_KEY = f"{DOMAIN}.data"
STORAGE_VERSION = 1

PANEL_URL = "argus"
API_LEVEL = 1          # raise together with API_LEVEL in the panel when the panel needs new server commands
PANEL_ELEMENT = "argus-panel"
STATIC_URL = f"/{DOMAIN}_static"

# Product categories: a shop lists the categories it sells, a product has one. A product is only searched
# at the shops of its category (a book is not looked up at an electronics store).
CATEGORIES: dict[str, str] = {
    "electronics": "Electronics",
    "books": "Books",
    "toys_games": "Toys & games",
    "home_garden_diy": "Home, garden & DIY",
    "other": "Other",
}
DEFAULT_CATEGORY = "other"

CONF_DISCOUNT_THRESHOLD = "discount_threshold"
CONF_DIGEST_TIME = "digest_time"
CONF_MIN_HISTORY_DAYS = "min_history_days"
CONF_IMPERSONATE = "use_impersonation"
CONF_NOTIFY = "notify_service"
CONF_RELAY = "browser_relay"                # userscript fetches shop pages from the user's browser
CONF_RELAY_HOURS = "relay_hours"
DEFAULT_RELAY_HOURS = 6
CONF_RETAILERS = "retailers"
CONF_TICKER = "ticker"                      # bottom ticker: {"drops": bool, "deals": bool, "news": bool, "max_*": int}
TICKER_RELOAD = 600                        # the ticker's content is reloaded every 10 minutes
TICKER_GOOD_SCORE = 45                     # a product shows in the ticker from this deal score (good price)
TICKER_DEFAULT = {"deals": True, "drops": True, "news": True, "max_deals": 3, "max_drops": 3, "max_news": 3, "shuffle": True}
CONF_BLOCK_WORDS = "block_words"            # your own words: a product title with one of these is never the product
CONF_ALLOW_WORDS = "allow_words"            # exceptions: words that may appear in a real product's title
CONF_AUTO_REFRESH = "auto_refresh"
CONF_REFRESH_TIMES = "refresh_times"
CONF_REFRESH_MODE = "refresh_mode"          # spread | times | off
CONF_SPREAD_HOURS = "spread_hours"
DEFAULT_REFRESH_MODE = "spread"
DEFAULT_SPREAD_HOURS = 6
CONF_DEAL_MIN_SCORE = "deal_min_score"      # a deal: deal score at least … (0-100)
CONF_DEAL_ATL = "deal_atl"                  # … or the lowest price ever counts as a deal
CONF_DEAL_TARGET = "deal_target"            # … or your target price reached counts as a deal
DEFAULT_DEAL_MIN_SCORE = 70
CYCLE_CHOICES = (2, 3, 4, 6, 12, 24)        # every product once per … hours
CONF_WATCH_CYCLE = "watch_cycle_min"        # priority products once per … minutes (0 = like the others)
WATCH_CYCLE_CHOICES = (0, 30, 60, 120, 180, 240, 360, 720, 1440)
PRODUCT_LIMIT = 200                         # products tracked at once (a friendly load on the shops)
FULL_REFRESH_GAP = 60                       # seconds between two full price rounds
MANUAL_GAP = 120                            # a manual fetch / search: once every 2 minutes (per action, per shop)
# developer mode (not in the regular settings)
CONF_DEV_FIXED_TIMES = "dev_fixed_times"    # allow full rounds at fixed times
CONF_DEV_FULL_REFRESH = "dev_full_refresh"  # allow "refresh all prices" by hand / service
CONF_DEV_FREE_CYCLE = "dev_free_cycle"      # any cycle 1–168 h instead of the choices
CONF_DEV_UNLIMITED = "dev_unlimited"        # no limit on the number of products
CONF_LANGUAGE = "language"
DEFAULT_REFRESH_TIMES = "07:30, 19:30"

DEFAULT_DISCOUNT_THRESHOLD = 20
DEFAULT_DIGEST_TIME = "08:00:00"
DEFAULT_MIN_HISTORY_DAYS = 3

# The shops come from the shop settings file the user imports (shops.apply_shop_options fills these):
# retailer id -> (label, currency)
RETAILERS: dict[str, tuple[str, str]] = {}
# shops read with the generic parser (JSON-LD / meta tags): id -> {"domain", "search"}
GENERIC_SHOPS: dict[str, dict[str, str]] = {}
# search URL per shop from the settings file. {query} = url-encoded name, {ean} = barcode.
DEFAULT_SEARCH: dict[str, str] = {}
CONF_CUSTOM_SHOPS = "custom_shops"          # [{"id","name","domain","search","categories"}]
CONF_SHOP_SEARCH = "shop_search"            # {shop_id: template} overrides
CONF_NO_AUTOPAUSE = "no_autopause"          # [shop_id] never auto-paused after a block
CONF_KNOWN_SHOPS = "known_shops"            # shops the user has seen (new ones get enabled once)

EVENT_DIGEST = f"{DOMAIN}_daily_digest"
EVENT_NEW_LOW = f"{DOMAIN}_new_all_time_low"
EVENT_HIGH_DISCOUNT = f"{DOMAIN}_price_drop"
EVENT_TARGET_HIT = f"{DOMAIN}_target_price_reached"
EVENT_JOB_DONE = f"{DOMAIN}_job_finished"

# Max price observations kept per offer (one per day is ~10 years).
MAX_HISTORY = 4000

# Deal alert per product: "tell me when it is suddenly this much cheaper than usual"
ALERT_STEPS = (10, 20, 30, 40, 50)
# Comparison sites: how often a product's offers are asked there, and how long their price may stand in for a shop
FINDER_ROUND_HOURS = 12
FINDER_PRICE_MAX_AGE = 72 * 3600
# A product is searched again every day at the shops where it has no confirmed page yet
REDISCOVER_HOURS = 24
