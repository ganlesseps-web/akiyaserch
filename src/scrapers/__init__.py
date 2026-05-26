from .base import Scraper, RawListing
from .minna_0en import MinnaZeroEnScraper
from .ieichiba import IeichibaScraper
from .iga_akiyabank import IgaAkiyabankScraper

REGISTRY: dict[str, type[Scraper]] = {
    "minna_0en": MinnaZeroEnScraper,
    "ieichiba": IeichibaScraper,
    "iga_akiyabank": IgaAkiyabankScraper,
}
