import time
from typing import List, Dict, Any
from camoufox.sync_api import Camoufox

from app.models import Offer
from app.plugins.aeromotors import AeromotorsPlugin
from app.plugins.intercars24 import Intercars24Plugin
from app.plugins.ladu24 import Ladu24Plugin

PLUGINS = [
    AeromotorsPlugin(),
    Intercars24Plugin(),
    Ladu24Plugin(),
]


def run_plugin(plugin, page, query: str):
    if plugin.site == "ladu24.ee":
        return plugin.search(query)
    return plugin.search(page, query)


def build_ean_candidates(query: str, offers: List[Offer]) -> List[str]:
    result = [query]
    seen = set(result)

    for o in offers:
        for e in o.ean:
            if not e:
                continue

            e = e.strip()

            if not e.isdigit():
                continue

            if e not in seen:
                seen.add(e)
                result.append(e)

    return result


def try_candidates(plugin, page, candidates: List[str]):
    for ean in candidates:
        print(f"   ↪ пробуем {ean}")
        offer = run_plugin(plugin, page, ean)
        if offer:
            print(f"   ↪ найдено по {ean}")
            return offer
    return None


def collect_offers(ean: str) -> List[Offer]:
    offers: List[Offer] = []
    missing = []

    with Camoufox(
        os=["windows", "macos", "linux"],
        headless=True,
        humanize=True,
    ) as browser:
        page = browser.new_page()

        print("\n=== ROUND 1 ===")
        for plugin in PLUGINS:
            start = time.time()

            try:
                print(f"\n🔍 [START] {plugin.site}")
                offer = run_plugin(plugin, page, ean)
                duration = round(time.time() - start, 2)

                if offer:
                    print(f"✅ [DONE] {plugin.site} за {duration}s")
                    offers.append(offer)
                else:
                    print(f"⚠️ [EMPTY] {plugin.site} за {duration}s")
                    missing.append(plugin)

            except Exception as e:
                print(f"❌ [ERROR] {plugin.site} | {e}")
                missing.append(plugin)

        new_missing = []
        new_found = []

        if missing and offers:
            print("\n=== ROUND 2 ===")
            candidates = build_ean_candidates(ean, offers)
            print(f"EAN candidates: {candidates}")

            for plugin in missing:
                start = time.time()

                try:
                    print(f"\n🔁 [RETRY] {plugin.site}")
                    offer = try_candidates(plugin, page, candidates)
                    duration = round(time.time() - start, 2)

                    if offer:
                        print(f"✅ [DONE] {plugin.site} за {duration}s")
                        offers.append(offer)
                        new_found.append(offer)
                    else:
                        print(f"⚠️ [EMPTY] {plugin.site} за {duration}s")
                        new_missing.append(plugin)

                except Exception as e:
                    print(f"❌ [ERROR] {plugin.site} | {e}")
                    new_missing.append(plugin)

        if new_missing and new_found:
            print("\n=== ROUND 3 ===")
            candidates = build_ean_candidates(ean, offers)
            print(f"EAN candidates: {candidates}")

            for plugin in new_missing:
                start = time.time()

                try:
                    print(f"\n🔁 [RETRY-2] {plugin.site}")
                    offer = try_candidates(plugin, page, candidates)
                    duration = round(time.time() - start, 2)

                    if offer:
                        print(f"✅ [DONE] {plugin.site} за {duration}s")
                        offers.append(offer)
                    else:
                        print(f"⚠️ [EMPTY] {plugin.site} за {duration}s")

                except Exception as e:
                    print(f"❌ [ERROR] {plugin.site} | {e}")

    return offers


def build_front_response(offers: List[Offer], query_ean: str) -> Dict[str, Any]:
    primary = offers[0]

    ean_set = set()
    for o in offers:
        for x in o.ean:
            if x and not x.upper().startswith("IC-"):
                ean_set.add(x.strip())

    return {
        "query_ean": query_ean,
        "product": {
            "brand": primary.brand,
            "part_number": primary.part_number,
            "name": primary.name,
            "category": primary.product_category,
            "ean": sorted(ean_set),
        },
        "offers": [
            {
                "site": o.site,
                "price": o.price,
                "url": o.url,
                "search_url": o.search_url,
                "status": o.status,
            }
            for o in offers
        ],
    }