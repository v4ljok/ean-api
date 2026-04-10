from typing import Optional, List
import base64
import json
import re

from app.models import Offer


def accept_osano(page) -> bool:
    btn = page.locator("button[datatest-id='tap-osano-accept']")
    try:
        btn.wait_for(state="visible", timeout=4000)
        btn.click()
        return True
    except Exception:
        if btn.count():
            try:
                btn.first.click(force=True)
                return True
            except Exception:
                try:
                    page.evaluate("""
                    () => {
                      const b = document.querySelector("button[datatest-id='tap-osano-accept']");
                      if (b) b.click();
                    }
                    """)
                    return True
                except Exception:
                    pass
        return False


def parse_status(page) -> str:
    try:
        el = page.locator("[data-availability]").first
        if el.count():
            value = el.get_attribute("data-availability")
            if value and value.strip().isdigit():
                qty = int(value.strip())
                return "Otsas" if qty == 0 else "Saadaval"
    except Exception:
        pass

    return "Puudub"


def safe_text(locator) -> str:
    try:
        if locator.count():
            value = locator.first.text_content()
            return value.strip() if value else ""
    except Exception:
        pass
    return ""


def safe_attr(locator, attr: str) -> str:
    try:
        if locator.count():
            value = locator.first.get_attribute(attr)
            return value.strip() if value else ""
    except Exception:
        pass
    return ""


def normalize_ean(value: str) -> str:
    return re.sub(r"\D", "", (value or "").strip())


def normalize_price(value: str) -> str:
    value = (value or "").strip().replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", value)
    return m.group(0) if m else ""


def split_eans(text: str) -> List[str]:
    if not text:
        return []

    parts = re.split(r"[,;/\n\r\t ]+", text)
    result = []
    seen = set()

    for part in parts:
        ean = normalize_ean(part)
        if ean and ean not in seen:
            seen.add(ean)
            result.append(ean)

    return result


def extract_price_from_jsonld(page) -> str:
    try:
        scripts = page.locator("script[type='application/ld+json']").all_text_contents()
        for raw in scripts:
            if not raw or not raw.strip():
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]

            for item in items:
                if not isinstance(item, dict):
                    continue

                if item.get("@type") == "Product":
                    offers = item.get("offers")
                    if isinstance(offers, dict):
                        price = offers.get("price")
                        if price:
                            normalized = normalize_price(str(price))
                            if normalized:
                                return normalized
    except Exception:
        pass

    return ""


def extract_prices_from_inline_json(page, art_value: str) -> tuple[str, str]:
    """
    Пытается достать цену из JS-блока:
    pricesFromApiStrictStr = JSON.stringify([...])
    Возвращает (gross_price, net_price)
    """
    try:
        html = page.content()
        if not html:
            return "", ""

        m = re.search(
            r"pricesFromApiStrictStr\s*=\s*JSON\.stringify\((\[.*?\])\)\s*;",
            html,
            flags=re.S,
        )
        if not m:
            return "", ""

        arr = json.loads(m.group(1))
        if not isinstance(arr, list):
            return "", ""

        target_art = (art_value or "").strip()

        for item in arr:
            if not isinstance(item, dict):
                continue

            tow = str(item.get("Tow", "")).strip()
            if target_art and tow and tow != target_art:
                continue

            gross = normalize_price(str(item.get("Cena1B", "") or item.get("PriceModal", "")))
            net = normalize_price(str(item.get("Cena1N", "")))
            return gross, net
    except Exception:
        pass

    return "", ""


def extract_eans_from_product_page(page) -> List[str]:
    selectors = [
        "div.attribute:has(strong:has-text('Vöötkood')) div.js-attr-color_multiselect",
        "div.attribute:has(strong:has-text('EAN')) div.js-attr-color_multiselect",
        "div.attribute:has(strong:has-text('Barcode')) div.js-attr-color_multiselect",
        "div.attribute:has(strong:has-text('Vöötkood'))",
        "div.attribute:has(strong:has-text('EAN'))",
        "div.attribute:has(strong:has-text('Barcode'))",
    ]

    for selector in selectors:
        text = safe_text(page.locator(selector))
        eans = split_eans(text)
        if eans:
            return eans

    return []


def find_best_card(page, ean: str):
    cards = page.locator("div[id^='check_view_price_param_']")
    count = 0

    try:
        count = cards.count()
    except Exception:
        count = 0

    if count == 0:
        return None

    wanted_ean = normalize_ean(ean)

    for i in range(count):
        card = cards.nth(i)

        try:
            text = card.text_content() or ""
        except Exception:
            text = ""

        if wanted_ean and wanted_ean in normalize_ean(text):
            return card

        try:
            html = card.inner_html()
        except Exception:
            html = ""

        if wanted_ean and wanted_ean in normalize_ean(html):
            return card

    return cards.first


class Intercars24Plugin:
    site = "intercars24.ee"

    def search(self, page, ean: str) -> Optional[Offer]:
        encoded = base64.b64encode(ean.encode()).decode()
        search_url = f"https://www.intercars24.ee/autoosad/search={encoded}&advancedOptionSearch=7"

        page.goto(search_url, wait_until="domcontentloaded")

        screenshot_bytes = page.screenshot(full_page=False, type="jpeg", quality=40)
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
        print("=== SCREENSHOT BASE64 PREVIEW START ===")
        print(f"{screenshot_b64[:200]}... [len={len(screenshot_b64)}]")
        print("=== SCREENSHOT BASE64 PREVIEW END ===")

        accept_osano(page)
        page.wait_for_timeout(1200)

        card = find_best_card(page, ean)
        if not card:
            return Offer(
                site=self.site,
                search_url=search_url,
                url="",
                name="",
                brand="",
                product_category="",
                part_number="",
                ean=[],
                price="",
                status="Puudub",
            )

        card_link = card.locator("a#main-link-product-card, a.main-link-product-card").first
        href = ""

        for _ in range(10):
            href = safe_attr(card_link, "href")
            if href:
                break
            page.wait_for_timeout(300)

        if not href:
            return Offer(
                site=self.site,
                search_url=search_url,
                url="",
                name="",
                brand="",
                product_category="",
                part_number="",
                ean=[],
                price="",
                status="Puudub",
            )

        url = href if href.startswith("http") else f"https://www.intercars24.ee{href}"

        listing_gross = normalize_price(
            safe_text(card.locator("div.value.price_gross_2.gross, div.price_gross_2.gross"))
        )
        listing_net = normalize_price(
            safe_text(card.locator("span.value.price_net_2.nett, span.price_net_2.nett"))
        )
        art_value = safe_attr(card.locator("input[id^='baner-item-art-']").first, "value")

        if not listing_gross:
            listing_gross, listing_net_from_json = extract_prices_from_inline_json(page, art_value)
            if not listing_net:
                listing_net = listing_net_from_json

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        name = safe_text(page.locator("h1"))
        brand = safe_text(page.locator("span.manufacture"))
        product_category = safe_text(page.locator("span[data-id='crumb2']"))

        price = listing_gross

        if not price:
            for _ in range(10):
                price = normalize_price(
                    safe_text(page.locator("div.value.price_gross_2.gross, div.price_gross_2.gross"))
                )
                if price:
                    break
                page.wait_for_timeout(250)

        if not price:
            page_gross, _ = extract_prices_from_inline_json(page, art_value)
            price = page_gross

        if not price:
            price = extract_price_from_jsonld(page)

        part_raw = safe_text(page.locator("span.indexValue"))
        if part_raw:
            cleaned = part_raw
            if brand:
                cleaned = re.sub(re.escape(brand), "", cleaned, flags=re.I)
            part_number = cleaned.strip(" -:/")
        else:
            part_number = ""

        show_btn = page.locator("#show-attributes-button-, #show-attributes-button-Tecdoc")
        if show_btn.count():
            try:
                show_btn.first.click()
                page.wait_for_timeout(400)
            except Exception:
                pass

        ean_list = extract_eans_from_product_page(page)

        if not ean_list:
            try:
                card_text = card.text_content() or ""
                ean_list = split_eans(card_text)
            except Exception:
                ean_list = []

        status = parse_status(page)

        wanted_ean = normalize_ean(ean)
        normalized_page_eans = {normalize_ean(x) for x in ean_list if normalize_ean(x)}

        if normalized_page_eans and wanted_ean and wanted_ean not in normalized_page_eans:
            return Offer(
                site=self.site,
                search_url=search_url,
                url="",
                name="",
                brand="",
                product_category="",
                part_number="",
                ean=[],
                price="",
                status="Puudub",
            )

        return Offer(
            site=self.site,
            search_url=search_url,
            url=url,
            name=name,
            brand=brand,
            product_category=product_category,
            part_number=part_number,
            ean=ean_list,
            price=price,
            status=status,
        )