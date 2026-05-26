from .base import Scraper, RawListing
from .minna_0en import MinnaZeroEnScraper

REGISTRY: dict[str, type[Scraper]] = {
    "minna_0en": MinnaZeroEnScraper,
}
