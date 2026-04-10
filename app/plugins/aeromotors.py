import io
from PIL import Image
from typing import Optional
import json
import re
import base64

from bs4 import BeautifulSoup

from app.models import Offer

def make_screenshot_base64(page, quality: int = 5) -> str:

        # ограничим диапазон (на всякий случай)
        quality = max(1, min(quality, 100))

        raw_bytes = page.screenshot(
            full_page=False,
            type="jpeg",
            quality=quality
        )

        # перевод в ч/б
        img = Image.open(io.BytesIO(raw_bytes)).convert("L")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)

        screenshot_bytes = buf.getvalue()
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        print("=== SCREENSHOT BASE64 PREVIEW START ===")
        print(screenshot_b64)
        print("=== SCREENSHOT BASE64 PREVIEW END ===")

        return screenshot_b64


class AeromotorsPlugin:
    site = "aeromotors.ee"

    def _clean_price(self, text: str) -> str:
        cleaned = text.replace("\xa0", " ").strip()
        cleaned = cleaned.replace("€", "").replace("EUR", "").strip()
        cleaned = cleaned.replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else ""

    def _extract_eans(self, value_cell) -> list[str]:
        return [x.strip() for x in value_cell.stripped_strings if x.strip()]
    
    def _is_cloudflare_verifying(self, page) -> bool:
        try:
            text = (page.text_content("body", timeout=1000) or "").lower()
            return (
                ("performing security verification" in text)
                or ("verifying" in text)
                or ("verify you are not a bot" in text)
                or (("cloudflare" in text) and ("checking" in text))
            )
        except Exception:
            return False

    def _handle_cloudflare_challenge(self, page) -> bool:
        cf_frame = None

        for _ in range(20):
            for frame in page.frames:
                if frame.url.startswith("https://challenges.cloudflare.com"):
                    cf_frame = frame
                    break
            if cf_frame:
                break

            if not self._is_cloudflare_verifying(page):
                return True

            page.wait_for_timeout(500)

        if cf_frame:
            try:
                frame_element = cf_frame.frame_element()
                if frame_element:
                    bbox = frame_element.bounding_box()
                    if bbox:
                        click_x = bbox["x"] + bbox["width"] / 9
                        click_y = bbox["y"] + bbox["height"] / 2
                        page.mouse.click(click_x, click_y)
            except Exception:
                pass

        for _ in range(120):
            iframe_exists = any(
                f.url.startswith("https://challenges.cloudflare.com")
                for f in page.frames
            )
            verifying = self._is_cloudflare_verifying(page)

            if not iframe_exists and not verifying:
                return True

            page.wait_for_timeout(500)

        return False

    def _parse_product(self, page, url: str) -> Optional[dict]:
        # domcontentloaded — не зависает на CF "Verifying..." в отличие от networkidle
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2000)

        ok = self._handle_cloudflare_challenge(page)
        if not ok:
            make_screenshot_base64(page, quality=5)
            return None

        soup = BeautifulSoup(page.content(), "html.parser")

        name_el = soup.select_one("h1")
        name = name_el.get_text(strip=True) if name_el else None

        brand = None
        product_category = None
        eans: list[str] = []
        part_number = None

        rows = soup.select("table tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) != 2:
                continue

            key = cols[0].get_text(" ", strip=True)
            value_cell = cols[1]

            if key == "Kaubamärk":
                strong = value_cell.select_one("strong")
                brand = strong.get_text(strip=True) if strong else value_cell.get_text(" ", strip=True)

            elif key == "Tootegrupp":
                strong = value_cell.select_one("strong")
                product_category = strong.get_text(strip=True) if strong else value_cell.get_text(" ", strip=True)

            elif key == "EAN":
                eans = self._extract_eans(value_cell)

        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text()
            if not raw.strip():
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            candidates = data if isinstance(data, list) else [data]

            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Product":
                    part_number = item.get("mpn") or item.get("sku")

                    if not brand:
                        brand_data = item.get("brand")
                        if isinstance(brand_data, dict):
                            brand = brand_data.get("name")

                    if not eans:
                        gtin13 = item.get("gtin13")
                        if gtin13:
                            eans = [gtin13]
                    break

            if part_number:
                break

        return {
            "name": name,
            "brand": brand,
            "product_category": product_category,
            "part_number": part_number,
            "ean": eans,
        }

    def search(self, page, ean: str) -> Optional[Offer]:
        search_url = f"https://aeromotors.ee/otsi?s={ean}"

        page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2500)

        ok = self._handle_cloudflare_challenge(page)
        if not ok:
            make_screenshot_base64(page, quality=5)
            return None

        make_screenshot_base64(page, quality=5)

        soup = BeautifulSoup(page.content(), "html.parser")

        not_found_el = soup.select_one(".am-products-header span")
        if not_found_el and "Tooteid ei leitud" in not_found_el.get_text(" ", strip=True):
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

        product = soup.select_one(".uk-product-card-horizontal")
        if not product:
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

        title_el = product.select_one(".product__title")
        price_el = product.select_one("p.uk-h4.uk-margin-remove")

        if not title_el or not price_el:
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

        title = title_el.get_text(strip=True)
        price = self._clean_price(price_el.get_text())
        link = title_el.get("href")

        if not link:
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

        if link.startswith("/"):
            link = f"https://aeromotors.ee{link}"
        elif not link.startswith("http"):
            link = f"https://aeromotors.ee/{link.lstrip('/')}"

        product_data = self._parse_product(page, link)
        if not product_data:
            return None
        
        return Offer(
            site=self.site,
            search_url=search_url,
            url=link,
            name=product_data["name"] or title,
            brand=product_data["brand"] or "",
            product_category=product_data["product_category"] or "",
            part_number=product_data["part_number"] or "",
            ean=product_data["ean"],
            price=price,
            status="Saadaval",
        )