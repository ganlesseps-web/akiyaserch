"""「DBに入れない・DBから消す」ルールを1か所に集約する。

scrape 側のスキップと purge 側の削除で**同じ条件**を使うことが重要。
条件がズレると「消したのに翌朝また入ってくる」事故になる。

対象 (2026-08-13 ユーザー指示):
- 土地だけの物件 (property_type='land') … 価格に関係なく不要
- 300万円以上の物件 … 予算外。※価格不明(NULL)は「300万以上と確定していない」ので残す

守るもの:
- ★お気に入り / 星評価 を付けた物件は、条件に当てはまっても削除しない
  (自分で意思表示したものが勝手に消えないように)
"""
from __future__ import annotations

from typing import Any

from . import db

PRICE_CUTOFF_YEN = 3_000_000  # config/filters.yaml の price_max と揃える (テストで担保)

# properties.id を参照する子テーブル。
# ※本番(Turso/libsql)は ON DELETE CASCADE が効かない(接続ごとに PRAGMA が引き継がれない)ため、
#   親を消す前にここを明示的に消す必要がある。drive_cache は address が主キーで
#   物件に紐づかない共有キャッシュなので対象外。
CHILD_TABLES = (
    "notifications",
    "read_status",
    "dismissed",
    "ratings",
    "ai_scores",
    "resale_ai",
    "price_drops",
)


def should_skip(listing: db.Listing, *, price_cutoff: int = PRICE_CUTOFF_YEN) -> str | None:
    """DBに入れない物件なら理由を返す。入れてよければ None。

    scrape の取り込み時に使う (これが無いと purge しても翌朝復活する)。
    """
    if listing.property_type == "land":
        return "土地"
    if listing.price is not None and listing.price >= price_cutoff:
        return "300万円以上"
    return None


def _target_sql(*, keep_rated: bool = True) -> str:
    """削除対象の id を選ぶ SELECT (パラメータは price_cutoff 1個)。

    NOT IN ではなく NOT EXISTS を使う (NOT IN は NULL が混ざると全件不一致になる罠がある)。
    """
    sql = (
        "SELECT p.id FROM properties p"
        " WHERE (p.property_type = 'land'"
        "        OR (p.price IS NOT NULL AND p.price >= ?))"
        "   AND NOT EXISTS (SELECT 1 FROM favorites f WHERE f.property_id = p.id)"
    )
    if keep_rated:
        sql += "   AND NOT EXISTS (SELECT 1 FROM ratings r WHERE r.property_id = p.id)"
    return sql


def count_targets(
    conn: Any, *, price_cutoff: int = PRICE_CUTOFF_YEN, keep_rated: bool = True
) -> dict[str, Any]:
    """削除の下見。実際には何も消さない。"""
    tgt = _target_sql(keep_rated=keep_rated)

    total = conn.execute(
        f"SELECT COUNT(*) FROM ({tgt})", (price_cutoff,)
    ).fetchone()[0]
    land = conn.execute(
        f"SELECT COUNT(*) FROM properties p WHERE p.property_type='land' AND p.id IN ({tgt})",
        (price_cutoff,),
    ).fetchone()[0]
    land_no_price = conn.execute(
        f"SELECT COUNT(*) FROM properties p WHERE p.property_type='land'"
        f" AND p.price IS NULL AND p.id IN ({tgt})",
        (price_cutoff,),
    ).fetchone()[0]
    pricey = conn.execute(
        f"SELECT COUNT(*) FROM properties p WHERE p.price IS NOT NULL AND p.price >= ?"
        f" AND p.id IN ({tgt})",
        (price_cutoff, price_cutoff),
    ).fetchone()[0]
    both = land + pricey - total if (land + pricey) >= total else 0

    protected = conn.execute(
        "SELECT COUNT(*) FROM properties p"
        " WHERE (p.property_type='land' OR (p.price IS NOT NULL AND p.price >= ?))"
        "   AND (EXISTS (SELECT 1 FROM favorites f WHERE f.property_id = p.id)"
        "        OR EXISTS (SELECT 1 FROM ratings r WHERE r.property_id = p.id))",
        (price_cutoff,),
    ).fetchone()[0]

    all_active = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]

    children: dict[str, int] = {}
    for t in CHILD_TABLES:
        children[t] = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE property_id IN ({tgt})", (price_cutoff,)
        ).fetchone()[0]

    # 土地判定の誤爆確認用サンプル (種別は本文からの推測なので目視できるようにする)
    land_samples = [
        (r["title"], r["price"], r["url"])
        for r in conn.execute(
            f"SELECT title, price, url FROM properties p"
            f" WHERE p.property_type='land' AND p.id IN ({tgt}) LIMIT 20",
            (price_cutoff,),
        ).fetchall()
    ]

    return {
        "all": all_active,
        "total": total,
        "land": land,
        "land_no_price": land_no_price,
        "pricey": pricey,
        "both": both,
        "protected": protected,
        "children": children,
        "land_samples": land_samples,
        "remaining": all_active - total,
    }


def purge(
    conn: Any, *, price_cutoff: int = PRICE_CUTOFF_YEN, keep_rated: bool = True
) -> int:
    """実際に削除する。子テーブル → 物件 の順 (途中で落ちても再実行で完了できる)。

    本番(libsql)はトランザクションが無く1文ずつ確定するため、順序と冪等性で守る。
    """
    tgt = _target_sql(keep_rated=keep_rated)
    for t in CHILD_TABLES:
        conn.execute(f"DELETE FROM {t} WHERE property_id IN ({tgt})", (price_cutoff,))
    conn.execute(f"DELETE FROM properties WHERE id IN ({tgt})", (price_cutoff,))
    return 0


def render_report(stats: dict[str, Any], *, applied: bool) -> str:
    """下見の結果を、プログラムを知らない人にも読める日本語で。"""
    head = "== 削除しました ==" if applied else "== 削除の下見 (まだ何も消していません) =="
    where = "Turso (本番)" if db.using_libsql() else f"ローカル ({db.db_path()})"
    lines = [
        head,
        f"接続先        : {where}",
        f"物件の総数    : {stats['all']:,} 件",
        "",
        f"削除の対象    : {stats['total']:,} 件",
        f"  ├ 土地だけの物件   : {stats['land']:,} 件"
        f" (うち価格が不明なもの {stats['land_no_price']:,} 件)",
        f"  ├ 300万円以上      : {stats['pricey']:,} 件",
        f"  └ 両方に当てはまる : {stats['both']:,} 件  ← 上2つの重複分",
        "",
        f"守られた物件  : {stats['protected']:,} 件 (★お気に入り・星評価を付けたものは消しません)",
        f"残る物件      : {stats['remaining']:,} 件",
        "",
        "一緒に消える関連データ:",
        "  " + " / ".join(f"{t} {n}" for t, n in stats["children"].items()),
    ]
    if stats.get("land_samples"):
        lines += [
            "",
            "「土地」と判定された物件の例 (種別は本文からの推測なので誤判定がないか確認用):",
        ]
        for title, price, _url in stats["land_samples"][:10]:
            p = f"{price:,}円" if price is not None else "価格不明"
            lines.append(f"  - [{p}] {(title or '')[:44]}")
    return "\n".join(lines)
