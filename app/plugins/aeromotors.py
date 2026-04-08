from typing import Optional
import json
import re

from bs4 import BeautifulSoup

from app.models import Offer


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

    def _parse_product(self, page, url: str) -> dict:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
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

        page.goto(search_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
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

        product_data = self._parse_product(page, link)

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