from typing import Optional
import re

import httpx
from bs4 import BeautifulSoup

from app.models import Offer


class Ladu24Plugin:
    site = "ladu24.ee"

    def _clean_price(self, text: str) -> str:
        cleaned = text.replace("\xa0", " ").strip()
        cleaned = cleaned.replace("€", "").replace("EUR", "").strip()
        cleaned = cleaned.replace(",", ".")

        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else ""

    def _abs_url(self, url: str) -> str:
        if url.startswith("http"):
            return url
        return "https://www.ladu24.ee" + url

    def _parse_product_page(self, url: str) -> dict:
        r = httpx.get(url, timeout=15, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        title_tag = soup.select_one("title")
        meta_desc = soup.select_one('meta[name="description"]')

        title = title_tag.get_text(strip=True) if title_tag else ""
        description = meta_desc.get("content", "").strip() if meta_desc else ""

        clean_title = title.replace(" - Ladu24.ee", "").strip()

        brand = ""
        part_number = ""

        m = re.search(r"(.+?)\s+([A-Za-z0-9]+)$", clean_title)
        if m:
            part_number = m.group(2).strip()

        if clean_title:
            parts = clean_title.split()
            if len(parts) >= 2 and part_number and part_number in parts:
                idx = parts.index(part_number)
                if idx > 0:
                    brand = parts[idx - 1]

        return {
            "name": clean_title,
            "brand": brand,
            "part_number": part_number,
            "description": description,
            "ean": [],
        }

    def search(self, ean: str) -> Optional[Offer]:
        search_url = f"https://www.ladu24.ee/varuosad/0/,,,,{ean}"

        r = httpx.get(search_url, timeout=15, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        product = soup.select_one(".productRow")
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

        title_el = product.select_one("a.productName")
        price_el = product.select_one("a.bg-light-green")
        brand_el = product.select_one(".productBrand")

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

        href = title_el.get("href", "").strip()
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

        link = self._abs_url(href)
        price = self._clean_price(price_el.get_text())
        fallback_name = title_el.get_text(" ", strip=True)
        fallback_brand = brand_el.get_text(strip=True) if brand_el else ""

        pills = product.select("span.btn.text-pill.bg-pill-grey")
        pill_texts = [x.get_text(" ", strip=True) for x in pills if x.get_text(" ", strip=True)]

        fallback_part_number = ""
        if pill_texts:
            fallback_part_number = pill_texts[-1]

        product_data = self._parse_product_page(link)

        return Offer(
            site=self.site,
            search_url=search_url,
            url=link,
            name=product_data["name"] or fallback_name,
            brand=product_data["brand"] or fallback_brand,
            product_category="",
            part_number=product_data["part_number"] or fallback_part_number,
            ean=product_data["ean"],
            price=price,
            status="Saadaval",
        )