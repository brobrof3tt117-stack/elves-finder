#!/usr/bin/env python3
"""
Elves Sealed Finder: hourly eBay updater.

GitHub runs this file automatically every hour. You never need to run it yourself.
It asks eBay's official Browse API for new, sealed LEGO Elves listings, keeps only
trustworthy sellers, and saves the results to site/data/listings.json for the website.

Settings you might want to change live in updater/settings.json.
The list of sets lives in site/data/sets.json.
"""

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
SETS_FILE = ROOT / "site" / "data" / "sets.json"
OUT_FILE = ROOT / "site" / "data" / "listings.json"
SETTINGS_FILE = ROOT / "updater" / "settings.json"
HEARTBEAT_FILE = ROOT / "updater" / "last-run-day.txt"
IMAGES_FILE = ROOT / "updater" / "set-images.json"
SHIPPING_FILE = ROOT / "updater" / "shipping-cache.json"

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_US"
CONDITION_NEW = "1000"  # eBay's code for "New": brand new, unopened, factory sealed
PAGE_SIZE = 200
MAX_PAGES = 25  # up to 5,000 results per search, far more than eBay ever has for Elves
LEGO_SETS_CATEGORY = "19006"  # eBay category "LEGO Complete Sets & Packs"

# Two broad searches cover the whole theme, then each listing is matched to its set here.
# This uses about 10 to 20 eBay calls per update instead of 80+, so it can share
# a keyset with other tools without running out of the 5,000 daily calls.
BROAD_SEARCHES = [
    {"q": "lego elves", "category_ids": LEGO_SETS_CATEGORY},
    {"category_ids": LEGO_SETS_CATEGORY, "aspect_filter": "categoryId:" + LEGO_SETS_CATEGORY + ",LEGO Theme:{Elves}"},
]
TIMEOUT = 30

# Official set pictures come from the LEGO wiki on Fandom (Brickipedia).
FANDOM_API = "https://lego.fandom.com/api.php"
FANDOM_HEADERS = {"User-Agent": "SealedElvesFinder/1.0 (personal hobby site; looks up each set picture once)"}

# Small words ignored when matching a set by its name.
STOPWORDS = {"the", "and", "of", "from", "a", "an", "his", "her", "s", "mr", "with", "lego", "elve", "elf"}
# Words that tell us a magazine gift is still in its original pack.
PACK_WORDS = {"magazine", "foil", "polybag", "pack", "bag", "sealed", "promo", "nisb", "misb", "nib"}


class AuthError(Exception):
    """eBay rejected the keys. Retrying will not help."""


class TemporaryError(Exception):
    """eBay or the network had a hiccup. Worth trying again next hour."""


# ===== text helpers =====

def normalize(text):
    """Lowercase, and turn every run of punctuation or spaces into one space."""
    out = []
    prev_space = True
    for ch in (text or "").lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch)
            prev_space = False
        elif not prev_space:
            out.append(" ")
            prev_space = True
    return "".join(out).strip()


def stem(word):
    """Very small plural/possessive trim so 'dragons' matches 'dragon' and 'airas' matches 'aira'."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def name_match_words(set_info):
    if set_info.get("match_words"):
        return [stem(normalize(w)) for w in set_info["match_words"]]
    words = [stem(w) for w in normalize(set_info["name"]).split()]
    return [w for w in words if w not in STOPWORDS and not w.isdigit()]


def contains_phrase(padded_text, phrase):
    p = normalize(phrase)
    return bool(p) and f" {p} " in padded_text


# ===== filters =====

def title_problem(title, settings, kind):
    """Return a short reason if the title suggests the item is NOT a sealed set, else None."""
    padded = f" {normalize(title)} "
    for ok in settings["ok_phrases"]:
        p = normalize(ok)
        if p:
            padded = padded.replace(f" {p} ", " ")
    for word in settings["hide_words"]:
        if contains_phrase(padded, word):
            return f"hide word: {word}"
    if kind != "Magazine gift":
        has_sealed_word = any(contains_phrase(padded, w) for w in settings["sealed_words"])
        if not has_sealed_word:
            for word in settings["maybe_hide_words"]:
                if contains_phrase(padded, word):
                    return f"maybe hide word: {word}"
    return None


def mentions_box_damage(title, settings):
    padded = f" {normalize(title)} "
    return any(contains_phrase(padded, w) for w in settings["box_warning_words"])


def title_is_this_set(title, set_info, known_numbers):
    """True if the listing title is about this exact set (and no other Elves set)."""
    toks = normalize(title).split()
    tokset = set(toks)
    number = set_info["number"]
    if (tokset & known_numbers) - {number}:
        return False  # mentions a different Elves set too, so it is a bundle or the wrong set
    if any(t.isdigit() and 5 <= len(t) <= 6 and t != number for t in toks):
        return False  # mentions another LEGO set number (like 60066), so it is a bundle
    stems = {stem(t) for t in toks}
    if number in tokset:
        # Loose parts often say only the number ("Baby Miku ELVES 41077"), so the
        # title must also share at least one word with the set's name.
        words = name_match_words(set_info)
        return not words or any(w in stems for w in words)
    if "elve" not in stems and "elf" not in stems:
        return False
    words = name_match_words(set_info)
    if not words or not all(w in stems for w in words):
        return False
    if set_info["kind"] == "Magazine gift" and not (stems & {stem(w) for w in PACK_WORDS}):
        return False
    return True


def seller_ok(seller, settings):
    try:
        pct = float(seller.get("feedbackPercentage"))
        count = int(seller.get("feedbackScore"))
    except (TypeError, ValueError):
        return False, None, None  # no rating info, so we cannot call them reliable
    ok = pct >= float(settings["min_seller_positive_percent"]) and count >= int(settings["min_seller_ratings"])
    return ok, pct, count


def money(obj):
    try:
        return round(float(obj["value"]), 2), obj.get("currency", "USD")
    except (TypeError, KeyError, ValueError):
        return None, None


def shipping_cost(item):
    """Cheapest shipping cost, 0.0 for free, or None if eBay gave no price.
    When a ship-to ZIP is set, eBay prices calculated shipping for that ZIP,
    so those prices are used too."""
    best = None
    for opt in item.get("shippingOptions") or []:
        value, _ = money(opt.get("shippingCost"))
        if value is not None and (best is None or value < best):
            best = value
    return best


def safe_url(url):
    return url if isinstance(url, str) and url.startswith("https://") else None


def to_listing(item, settings):
    """Turn one eBay search result into the small record the website shows."""
    options = item.get("buyingOptions") or []
    is_auction = "AUCTION" in options
    is_bin = "FIXED_PRICE" in options
    if is_auction and not settings["show_auctions"]:
        return None
    if is_bin and not is_auction and not settings["show_buy_it_now"]:
        return None
    if not is_auction and not is_bin:
        return None

    if is_auction:
        price, currency = money(item.get("currentBidPrice"))
        if price is None:
            price, currency = money(item.get("price"))
    else:
        price, currency = money(item.get("price"))
    if price is None or currency != "USD":
        return None

    url = safe_url(item.get("itemWebUrl"))
    if not url:
        return None
    image = safe_url((item.get("image") or {}).get("imageUrl"))
    if not image:
        thumbs = item.get("thumbnailImages") or []
        image = safe_url(thumbs[0].get("imageUrl")) if thumbs else None

    _, pct, count = seller_ok(item.get("seller") or {}, settings)
    bids = item.get("bidCount")
    return {
        "id": str(item.get("itemId", "")),
        "title": item.get("title", ""),
        "url": url,
        "image": image,
        "price": price,
        "shipping": shipping_cost(item),
        "kind": "Auction" if is_auction else "Buy It Now",
        "best_offer": "BEST_OFFER" in options,
        "bids": int(bids) if isinstance(bids, int) else (0 if is_auction else None),
        "ends": item.get("itemEndDate") if is_auction else None,
        "listed": item.get("itemCreationDate"),
        "seller_percent": pct,
        "seller_ratings": count,
        "box_note": mentions_box_damage(item.get("title", ""), settings),
    }


def keep_item(item, set_info, known_numbers, settings):
    """All the checks in one place. Returns a listing dict or None."""
    if str(item.get("conditionId", "")) != CONDITION_NEW:
        return None
    if settings["us_sellers_only"] and (item.get("itemLocation") or {}).get("country") != "US":
        return None
    title = item.get("title", "")
    if not title_is_this_set(title, set_info, known_numbers):
        return None
    if title_problem(title, settings, set_info["kind"]):
        return None
    ok, _, _ = seller_ok(item.get("seller") or {}, settings)
    if not ok:
        return None
    return to_listing(item, settings)


# ===== eBay calls =====

class Ebay:
    def __init__(self, client_id, client_secret, session=None, sleep=time.sleep, zip_code=""):
        self.zip_code = zip_code if zip_code.isdigit() and len(zip_code) == 5 else ""
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self.sleep = sleep
        self.token = None
        self.calls = 0

    def headers(self):
        h = {"Authorization": f"Bearer {self.token}", "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
        if self.zip_code:
            # Tells eBay where the buyer is, so shipping is priced for that ZIP.
            h["X-EBAY-C-ENDUSERCTX"] = f"contextualLocation=country%3DUS%2Czip%3D{self.zip_code}"
        return h

    def refresh_token(self):
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        last = "unknown problem"
        for attempt in range(4):
            try:
                r = self.session.post(
                    TOKEN_URL,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": f"Basic {auth}",
                    },
                    data={"grant_type": "client_credentials", "scope": SCOPE},
                    timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                last = f"network error: {e}"
                self.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 200:
                self.token = r.json()["access_token"]
                return
            if r.status_code in (400, 401, 403):
                raise AuthError(f"eBay rejected the keys ({r.status_code}): {r.text[:300]}")
            last = f"eBay answered {r.status_code}"
            self.sleep(2 * (attempt + 1))
        raise TemporaryError(f"Could not get an eBay token: {last}")

    def get(self, url, params=None):
        if not self.token:
            self.refresh_token()
        refreshed = False
        last = "unknown problem"
        for attempt in range(4):
            self.calls += 1
            try:
                r = self.session.get(
                    url,
                    params=params,
                    headers=self.headers(),
                    timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                last = f"network error: {e}"
                self.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and not refreshed:
                self.refresh_token()
                refreshed = True
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"eBay answered {r.status_code}"
                self.sleep(3 * (attempt + 1))
                continue
            raise TemporaryError(f"eBay answered {r.status_code}: {r.text[:300]}")
        raise TemporaryError(last)

    def get_item(self, item_id):
        """Full details of one listing. With a ship-to ZIP this includes the real
        shipping price to that ZIP, which search results leave out."""
        return self.get(ITEM_URL + quote(item_id, safe=""))

    def search(self, search_params, settings):
        options = []
        if settings["show_buy_it_now"]:
            options.append("FIXED_PRICE")
        if settings["show_auctions"]:
            options.append("AUCTION")
        filters = [f"conditionIds:{{{CONDITION_NEW}}}", f"buyingOptions:{{{'|'.join(options)}}}"]
        if settings["us_sellers_only"]:
            filters += ["itemLocationCountry:US", "deliveryCountry:US"]
        params = dict(search_params)
        params.update({"limit": str(PAGE_SIZE), "filter": ",".join(filters)})
        items = []
        data = self.get(SEARCH_URL, params)
        pages = 1
        while True:
            items.extend(data.get("itemSummaries") or [])
            nxt = data.get("next")
            if not nxt or pages >= MAX_PAGES:
                break
            data = self.get(nxt)
            pages += 1
        return items


def match_set(title, sets, known_numbers):
    """Which one set is this listing about? None if it matches zero sets or more than one."""
    hits = [s for s in sets if title_is_this_set(title, s, known_numbers)]
    return hits[0] if len(hits) == 1 else None


def fetch_all(ebay, sets, known_numbers, settings):
    """Run the broad searches and sort every good listing into its set.
    Returns (listings by set number, number of searches that worked)."""
    by_set = {s["number"]: [] for s in sets}
    seen = set()
    worked = 0
    for search_params in BROAD_SEARCHES:
        try:
            items = ebay.search(search_params, settings)
        except TemporaryError as e:
            print(f"One of the searches failed this hour ({e})")
            continue
        worked += 1
        for item in items:
            item_id = item.get("itemId")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            set_info = match_set(item.get("title", ""), sets, known_numbers)
            if not set_info:
                continue
            listing = keep_item(item, set_info, known_numbers, settings)
            if listing:
                by_set[set_info["number"]].append(listing)
    for listings in by_set.values():
        listings.sort(key=lambda x: x["price"] + (x["shipping"] or 0))
    return by_set, worked


# ===== exact shipping for listings with calculated shipping =====

def load_shipping_cache():
    try:
        data = json.loads(SHIPPING_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def fill_shipping(ebay, by_set, settings):
    """Search results have no price for calculated shipping, so look those listings up
    one by one (cheapest first, a few per update) and remember the answer.
    A listing's shipping to the same ZIP does not change, so each costs one lookup ever.
    Returns how many lookups were made."""
    cache = load_shipping_cache()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    limit = int(settings.get("max_shipping_lookups_per_update", 10))
    listings = [l for ls in by_set.values() for l in ls]
    current_ids = {l["id"] for l in listings}
    for l in listings:
        hit = cache.get(l["id"])
        if l["shipping"] is None and hit and hit.get("shipping") is not None:
            l["shipping"] = hit["shipping"]
    todo = [l for l in listings if l["shipping"] is None and (cache.get(l["id"]) or {}).get("checked") != today]
    todo.sort(key=lambda l: l["price"])
    looked = 0
    for l in todo[:max(0, limit)]:
        try:
            detail = ebay.get_item(l["id"])
        except TemporaryError as e:
            print(f"Shipping lookup paused this hour ({e})")
            break
        looked += 1
        cost = shipping_cost(detail)
        cache[l["id"]] = {"shipping": cost, "checked": today}
        if cost is not None:
            l["shipping"] = cost
    cache = {k: v for k, v in cache.items() if k in current_ids}  # forget sold or ended listings
    try:
        SHIPPING_FILE.write_text(json.dumps(cache, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as e:
        print(f"Could not save shipping-cache.json ({e})")
    for ls in by_set.values():
        ls.sort(key=lambda x: x["price"] + (x["shipping"] or 0))
    missing = sum(1 for l in listings if l["shipping"] is None)
    print(f"Shipping: looked up {looked} listing(s) this update, {missing} still waiting for a price.")
    return looked


# ===== set pictures from Fandom =====

def fandom_picture(session, number):
    """Ask the LEGO Fandom wiki for the main picture on the page of this set number.
    Returns an https picture address, or None if the wiki has no page or picture for it."""
    r = session.get(
        FANDOM_API,
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": number,
            "gsrnamespace": "0",
            "gsrlimit": "10",
            "prop": "pageimages",
            "piprop": "original",
        },
        headers=FANDOM_HEADERS,
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        raise TemporaryError(f"Fandom answered {r.status_code}")
    pages = ((r.json().get("query") or {}).get("pages") or {}).values()
    for page in sorted(pages, key=lambda p: p.get("index", 99)):
        title = page.get("title", "")
        if title == number or title.startswith(number + " "):
            return safe_url((page.get("original") or {}).get("source"))
    return None


def load_images():
    try:
        data = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update_images(sets, session=None):
    """Looks up each set picture once and remembers it in updater/set-images.json.
    Sets with no picture yet are retried once a day. Never stops the eBay update."""
    cache = load_images()
    session = session or requests.Session()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changed = False
    for s in sets:
        entry = cache.get(s["number"]) or {}
        if entry.get("url") or entry.get("checked") == today:
            continue
        try:
            url = fandom_picture(session, s["number"])
        except Exception as e:  # any Fandom problem just means "try again tomorrow"
            print(f"Picture for {s['number']}: Fandom lookup failed ({e})")
            url = None
        cache[s["number"]] = {"url": url, "checked": today}
        changed = True
        print(f"Picture for {s['number']}: {'found' if url else 'none on Fandom, will use an eBay photo'}")
    if changed:
        IMAGES_FILE.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {n: e["url"] for n, e in cache.items() if e.get("url")}


# ===== main =====

def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


SHIP_TO_ZIP = os.environ.get("SHIP_TO_ZIP", "").strip()


def write_output(status, sets_out, settings, message="", images=None):
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": now_iso(),
        "status": status,
        "message": message,
        "rules": {
            "min_seller_positive_percent": settings["min_seller_positive_percent"],
            "min_seller_ratings": settings["min_seller_ratings"],
            "us_sellers_only": settings["us_sellers_only"],
            "shipping_for_zip": bool(SHIP_TO_ZIP.isdigit() and len(SHIP_TO_ZIP) == 5),
        },
        "images": images or {},
        "sets": sets_out,
    }
    tmp = OUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT_FILE)


def write_heartbeat():
    """Writes today's date once a day. GitHub turns off hourly jobs on repos with no
    changes for 60 days, so the workflow saves this tiny file daily to stay active."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    HEARTBEAT_FILE.write_text(today + "\n", encoding="utf-8")


def run(client_id, client_secret, session=None, sleep=time.sleep, fandom_session=None):
    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    sets = json.loads(SETS_FILE.read_text(encoding="utf-8"))["sets"]
    known_numbers = {s["number"] for s in sets}
    write_heartbeat()
    images = update_images(sets, fandom_session)

    if not client_id or not client_secret:
        print("No eBay keys found yet. Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET as GitHub secrets.")
        write_output("needs_keys", {}, settings, "eBay keys have not been added yet.", images)
        return 0

    ebay = Ebay(client_id, client_secret, session=session, sleep=sleep, zip_code=SHIP_TO_ZIP)
    try:
        ebay.refresh_token()
    except AuthError as e:
        print(f"PROBLEM: {e}")
        write_output("bad_keys", {}, settings, "eBay did not accept the keys.", images)
        return 0
    except TemporaryError as e:
        print(f"eBay is having trouble right now, keeping the last good results online. Details: {e}")
        return 1

    try:
        by_set, worked = fetch_all(ebay, sets, known_numbers, settings)
    except AuthError as e:
        print(f"PROBLEM: {e}")
        write_output("bad_keys", {}, settings, "eBay did not accept the keys.", images)
        return 0

    if worked == 0:
        print("Every search failed, so the last good results stay online.")
        return 1

    if ebay.zip_code:
        try:
            fill_shipping(ebay, by_set, settings)
        except AuthError:
            pass  # the listings are still good without exact shipping

    sets_out = {n: {"error": False, "listings": l} for n, l in by_set.items()}
    total = sum(len(l) for l in by_set.values())
    for s in sets:
        print(f"{s['number']} {s['name']}: {len(by_set[s['number']])} sealed listing(s)")
    write_output("ok", sets_out, settings, images=images)
    print(f"Done. {total} sealed listing(s) across {len(sets)} sets. eBay calls used this update: {ebay.calls}.")
    return 0


if __name__ == "__main__":
    sys.exit(run(os.environ.get("EBAY_CLIENT_ID", "").strip(), os.environ.get("EBAY_CLIENT_SECRET", "").strip()))
