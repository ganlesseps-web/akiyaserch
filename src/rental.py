"""賃貸 (2026-11-17 ユーザー「賃貸も探して欲しい」「家賃は6-7万円前後で」「間取りは3LDK以上」).

- 山梨県の賃貸一戸建てを集める (今は SUUMO)。price は月々の家賃＋管理費 (円)
- 家賃＋管理費が RENT_MAX 円を超える家、2部屋以下の家は取り込まない
- 再販・民泊向けの AI 判定 (出口・見送り) は買う家のための判定なので、賃貸には使わない
- ダッシュボードでは「🔑賃貸」タブだけに出す。Discord には通知する
"""
from __future__ import annotations

from typing import Any

RENT_MAX = 75_000   # 月7.5万円 (家賃＋管理費)

# 一覧から賃貸を外す / 賃貸だけにする条件
NOT_RENT_SQL = " AND (p.deal_type IS NULL OR p.deal_type != 'rent')"
ONLY_RENT_SQL = " AND p.deal_type = 'rent'"


def is_rent(row: Any) -> bool:
    try:
        return row["deal_type"] == "rent"
    except (KeyError, IndexError, ValueError, TypeError):
        return getattr(row, "deal_type", None) == "rent"
