from dataclasses import dataclass
from typing import List

@dataclass
class Offer:
    site: str
    search_url: str
    url: str
    name: str
    brand: str
    product_category: str
    part_number: str
    ean: List[str]
    price: str
    status: str