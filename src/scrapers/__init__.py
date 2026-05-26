from .base import Scraper, RawListing
from .minna_0en import MinnaZeroEnScraper
from .ieichiba import IeichibaScraper
from .iga_akiyabank import IgaAkiyabankScraper
from .akiya_athome import (
    KamikawaAkiyabankScraper,
    TakaAkiyabankScraper,
    TatsunoAkiyabankScraper,
    YabuAkiyabankScraper,
    FukuchiyamaAkiyabankScraper,
    MimasakaAkiyabankScraper,
)
from .kyotango_akiya import KyotangoAkiyaScraper
from .nabari_akiyabank import NabariAkiyabankScraper
from .takashima_akiya import TakashimaAkiyaScraper
from .gojo_akiyabank import GojoAkiyabankScraper
from .shimoichi_akiyabank import ShimoichiAkiyabankScraper
from .wakayama_life import WakayamaLifeScraper
from .yabu_indep import YabuIndepScraper

REGISTRY: dict[str, type[Scraper]] = {
    "minna_0en": MinnaZeroEnScraper,
    "ieichiba": IeichibaScraper,
    "iga_akiyabank": IgaAkiyabankScraper,
    "kamikawa_akiyabank": KamikawaAkiyabankScraper,
    "taka_akiyabank": TakaAkiyabankScraper,
    "tatsuno_akiyabank": TatsunoAkiyabankScraper,
    "yabu_akiyabank": YabuAkiyabankScraper,
    "fukuchiyama_akiyabank": FukuchiyamaAkiyabankScraper,
    "mimasaka_akiyabank": MimasakaAkiyabankScraper,
    "kyotango_akiya": KyotangoAkiyaScraper,
    "nabari_akiyabank": NabariAkiyabankScraper,
    "takashima_akiya": TakashimaAkiyaScraper,
    "gojo_akiyabank": GojoAkiyabankScraper,
    "shimoichi_akiyabank": ShimoichiAkiyabankScraper,
    "wakayama_life": WakayamaLifeScraper,
    "yabu_indep": YabuIndepScraper,
}
