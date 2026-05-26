from .base import Scraper, RawListing
from .minna_0en import MinnaZeroEnScraper
from .ieichiba import IeichibaScraper

REGISTRY: dict[str, type[Scraper]] = {
    "minna_0en": MinnaZeroEnScraper,
    "ieichiba": IeichibaScraper,
}
