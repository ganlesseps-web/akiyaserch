from .base import Scraper
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
    AyabeAkiyabankScraper,
    NishiawakuraAkiyabankScraper,
    NagiAkiyabankScraper,
    AsagoAkiyabankScraper,
    MaizuruAkiyabankScraper,
    MatsusakaAkiyabankScraper,
    ShisoAkiyabankScraper,
    MiyoshiAkiyabankScraper,
    MotoyamaAkiyabankScraper,
    MineAkiyabankScraper,
    HokutoAkiyabankScraper,
    HashimotoAkiyabankScraper,
    AkaiwaAkiyabankScraper,
)
from .takahashi_akiyabank import TakahashiAkiyabankScraper
from .kyotango_akiya import KyotangoAkiyaScraper
from .nabari_akiyabank import NabariAkiyabankScraper
from .takashima_akiya import TakashimaAkiyaScraper
from .gojo_akiyabank import GojoAkiyabankScraper
from .shimoichi_akiyabank import ShimoichiAkiyabankScraper
from .wakayama_life import WakayamaLifeScraper
from .yabu_indep import YabuIndepScraper
from .koka_iju import KokaIjuScraper
from .uda_akiyabank import UdaAkiyabankScraper
from .ohdai_awa import OhdaiAwaScraper
from .nancla import NanclaScraper
from .classo_tambasasayama import ClassoTambasasayamaScraper
from .higashiyoshino import HigashiyoshinoScraper
from .totsukawa import TotsukawaScraper

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
    "ayabe_akiyabank": AyabeAkiyabankScraper,
    "nishiawakura_akiyabank": NishiawakuraAkiyabankScraper,
    "nagi_akiyabank": NagiAkiyabankScraper,
    "asago_akiyabank": AsagoAkiyabankScraper,
    "maizuru_akiyabank": MaizuruAkiyabankScraper,
    "matsusaka_akiyabank": MatsusakaAkiyabankScraper,
    "shiso_akiyabank": ShisoAkiyabankScraper,
    "miyoshi_akiyabank": MiyoshiAkiyabankScraper,
    "motoyama_akiyabank": MotoyamaAkiyabankScraper,
    "mine_akiyabank": MineAkiyabankScraper,
    "hokuto_akiyabank": HokutoAkiyabankScraper,
    "hashimoto_akiyabank": HashimotoAkiyabankScraper,
    "kyotango_akiya": KyotangoAkiyaScraper,
    "nabari_akiyabank": NabariAkiyabankScraper,
    "takashima_akiya": TakashimaAkiyaScraper,
    "gojo_akiyabank": GojoAkiyabankScraper,
    "shimoichi_akiyabank": ShimoichiAkiyabankScraper,
    "wakayama_life": WakayamaLifeScraper,
    "yabu_indep": YabuIndepScraper,
    "koka_iju": KokaIjuScraper,
    "uda_akiyabank": UdaAkiyabankScraper,
    "ohdai_awa": OhdaiAwaScraper,
    "nancla": NanclaScraper,
    "classo_tambasasayama": ClassoTambasasayamaScraper,
    "higashiyoshino": HigashiyoshinoScraper,
    "totsukawa": TotsukawaScraper,
    "akaiwa_akiyabank": AkaiwaAkiyabankScraper,
    "takahashi_akiyabank": TakahashiAkiyabankScraper,
}
