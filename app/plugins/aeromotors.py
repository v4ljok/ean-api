from typing import Optional
import json
import re
import time
import random

from bs4 import BeautifulSoup

from app.models import Offer


class AeromotorsPlugin:
    site = "aeromotors.ee"
    base_url = "https://aeromotors.ee"

    # ------------------------------------------------------------------ #
    #  Утилиты                                                             #
    # ------------------------------------------------------------------ #

    def _clean_price(self, text: str) -> str:
        cleaned = text.replace("\xa0", " ").strip()
        cleaned = cleaned.replace("€", "").replace("EUR", "").strip()
        cleaned = cleaned.replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", cleaned)
        return match.group(0) if match else ""

    def _extract_eans(self, value_cell) -> list[str]:
        return [x.strip() for x in value_cell.stripped_strings if x.strip()]

    def _abs_url(self, link: str) -> str:
        if link.startswith("http"):
            return link
        return f"{self.base_url}/{link.lstrip('/')}"

    def _make_not_found(self, search_url: str) -> Offer:
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

    # ------------------------------------------------------------------ #
    #  Cloudflare                                                          #
    # ------------------------------------------------------------------ #

    def _is_cf_page(self, page) -> bool:
        """Проверяет, показывает ли страница CF-челлендж."""
        title = page.title().lower()
        if "just a moment" in title or "checking your browser" in title:
            return True
        if any("challenges.cloudflare.com" in f.url for f in page.frames):
            return True
        # inline-форма без отдельного фрейма
        try:
            if page.locator("#challenge-form").count() > 0:
                return True
        except Exception:
            pass
        return False

    def _wait_for_cf(self, page, timeout_s: int = 40) -> bool:
        """
        Ждёт пока CF-челлендж пройдёт сам (Camoufox с humanize=True
        обычно решает его автоматически).
        Возвращает True если страница очистилась.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not self._is_cf_page(page):
                return True
            page.wait_for_timeout(1000)
        return False

    # ------------------------------------------------------------------ #
    #  Навигация                                                           #
    # ------------------------------------------------------------------ #

    def _goto(self, page, url: str, retries: int = 3) -> bool:
        """
        Открывает страницу, ждёт окончания CF если нужно.
        Возвращает True при успехе.
        """
        for attempt in range(1, retries + 1):
            try:
                # domcontentloaded — не зависает на CF в отличие от networkidle
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                print(f"[aeromotors] goto error (attempt {attempt}): {e}")
                if attempt == retries:
                    return False
                page.wait_for_timeout(random.randint(2000, 4000))
                continue

            # короткая пауза чтобы CF успел инициализироваться
            page.wait_for_timeout(random.randint(1500, 2500))

            if self._is_cf_page(page):
                print(f"[aeromotors] CF challenge (attempt {attempt}), ждём...")
                resolved = self._wait_for_cf(page, timeout_s=45)
                if not resolved:
                    print("[aeromotors] CF не прошёл, ретрай")
                    page.wait_for_timeout(random.randint(3000, 6000))
                    continue

            return True

        return False

    # ------------------------------------------------------------------ #
    #  Парсинг страницы товара                                             #
    # ------------------------------------------------------------------ #

    def _parse_product(self, page, url: str) -> dict:
        ok = self._goto(page, url)
        if not ok:
            return {"name": None, "brand": None,
                    "product_category": None, "part_number": None, "ean": []}

        soup = BeautifulSoup(page.content(), "html.parser")

        name_el = soup.select_one("h1")
        name = name_el.get_text(strip=True) if name_el else None

        brand = None
        product_category = None
        eans: list[str] = []
        part_number = None

        for row in soup.select("table tr"):
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
            for item in (data if isinstance(data, list) else [data]):
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

    # ------------------------------------------------------------------ #
    #  Публичный метод                                                     #
    # ------------------------------------------------------------------ #

    def search(self, page, ean: str) -> Optional[Offer]:
        search_url = f"{self.base_url}/otsi?s={ean}"

        ok = self._goto(page, search_url, retries=3)
        if not ok:
            print(f"[aeromotors] не удалось загрузить {search_url}")
            return self._make_not_found(search_url)

        soup = BeautifulSoup(page.content(), "html.parser")

        # "Товаров не найдено"
        not_found_el = soup.select_one(".am-products-header span")
        if not_found_el and "Tooteid ei leitud" in not_found_el.get_text(" ", strip=True):
            return self._make_not_found(search_url)

        product = soup.select_one(".uk-product-card-horizontal")
        if not product:
            # Возможно CF всё же не прошёл — логируем
            print(f"[aeromotors] карточка не найдена, title={page.title()!r}")
            return self._make_not_found(search_url)

        title_el = product.select_one(".product__title")
        price_el = product.select_one("p.uk-h4.uk-margin-remove")

        if not title_el or not price_el:
            return self._make_not_found(search_url)

        title = title_el.get_text(strip=True)
        price = self._clean_price(price_el.get_text())
        link = title_el.get("href")

        if not link:
            return self._make_not_found(search_url)

        link = self._abs_url(link)
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
