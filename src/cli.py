"""CLI: trade scrape | notify | web | db init | launchd ..."""
from __future__ import annotations

import logging
import os
import sys

import click
from dotenv import load_dotenv

from . import db, filter as flt, normalize, purge as purge_rules
from .scrapers import REGISTRY
from .scrapers.base import make_client

load_dotenv()
logging.basicConfig(
    level=os.environ.get("TRADE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("trade")


@click.group()
def cli() -> None:
    """trade: 0円・格安物件 監視＆通知システム"""
    pass


@cli.command("db")
@click.argument("action", type=click.Choice(["init", "path"]))
def db_cmd(action: str) -> None:
    if action == "init":
        db.init_db()
        click.echo(f"initialized {db.db_path()}")
    elif action == "path":
        click.echo(str(db.db_path()))


@cli.command()
@click.argument("source", required=False)
def scrape(source: str | None) -> None:
    """指定ソース(or 全部)をスクレイプして DB に保存。"""
    db.init_db()
    sources = [source] if source else list(REGISTRY.keys())
    summary: dict[str, dict[str, int]] = {}
    with make_client() as client, db.connect() as conn:
        for name in sources:
            if name not in REGISTRY:
                click.echo(f"unknown source: {name}", err=True)
                sys.exit(2)
            scraper = REGISTRY[name]()
            stats = {"raw": 0, "new": 0, "updated": 0, "skipped": 0}
            for raw in scraper.fetch(client):
                stats["raw"] += 1
                listing = normalize.normalize(raw)
                # 土地だけ / 300万円以上 は DB に入れない (purge と同じルール)
                if purge_rules.should_skip(listing):
                    stats["skipped"] += 1
                    continue
                _pid, is_new = db.upsert_listing(conn, listing)
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1
            summary[name] = stats
            log.info("%s: %s", name, stats)
    for name, s in summary.items():
        click.echo(
            f"{name}: raw={s['raw']} new={s['new']} updated={s['updated']} skipped={s['skipped']}"
        )


@cli.command()
@click.option("--dry-run", is_flag=True, help="Discord に送らず stdout に出すだけ")
@click.option("--use-distance-matrix", is_flag=True, help="境界府県を Distance Matrix で詰める")
def notify(dry_run: bool, use_distance_matrix: bool) -> None:
    """未通知 & filter pass の物件を Discord に通知 (新着 + 値下げ)。"""
    from . import notifier_discord as nd
    cfg = flt.FilterConfig.load()
    with db.connect() as conn:
        stats = nd.notify(conn, cfg, dry_run=dry_run, use_distance_matrix=use_distance_matrix)
        drops = nd.notify_price_drops(
            conn, cfg, dry_run=dry_run, use_distance_matrix=use_distance_matrix
        )
    click.echo(f"new:        scanned={stats['scanned']} passed={stats['passed']} sent={stats['sent']}")
    click.echo(f"price_drop: scanned={drops['scanned']} passed={drops['passed']} sent={drops['sent']}")


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def web(host: str, port: int) -> None:
    """ローカルダッシュボード起動。"""
    import uvicorn
    uvicorn.run("src.web.app:app", host=host, port=port, reload=False)


@cli.command()
@click.option("--limit", default=100, type=int, help="一度にスコア付与する最大件数")
def score(limit: int) -> None:
    """AI で未スコア物件をスコア付け (preferences.yaml 基準。既定は Gemini 無料枠)。"""
    from . import llm, scorer
    cfg = scorer.PreferenceConfig.load()
    try:
        with db.connect() as conn:
            stats = scorer.score_unscored(conn, cfg, limit=limit)
    except llm.NoAPIKey as e:
        click.echo(f"スキップしました: {e}", err=True)
        return
    click.echo(f"target={stats['target']} scored={stats['scored']} failed={stats['failed']}")


@cli.command()
def reclassify() -> None:
    """既存物件の各判定 (種別/ボロ/即入居/要修繕/再販NG・警告) を再判定。"""
    db.init_db()  # ALTER TABLE が必要なら自動実行
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, body, property_type, dilapidated FROM properties"
        ).fetchall()
        type_counts: dict[str, int] = {}
        dilap_count = 0
        ready_count = 0
        repair_count = 0
        ng_count = 0
        warn_count = 0
        for r in rows:
            pt = normalize.classify_property_type(r["title"], r["body"])
            is_bad, reason = normalize.is_dilapidated(r["title"], r["body"])
            is_ready, ready_reason = normalize.is_move_in_ready(r["title"], r["body"])
            repair_needed, repair_reason = normalize.needs_repair(r["title"], r["body"])
            ng, ng_reason = normalize.detect_resale_ng(r["title"], r["body"])
            warnings = normalize.detect_resale_warnings(r["title"], r["body"])
            type_counts[pt] = type_counts.get(pt, 0) + 1
            if is_bad:
                dilap_count += 1
            if is_ready:
                ready_count += 1
            if repair_needed:
                repair_count += 1
            if ng:
                ng_count += 1
            if warnings:
                warn_count += 1
            conn.execute(
                "UPDATE properties SET property_type = ?, dilapidated = ?, dilapidation_reason = ?, "
                "move_in_ready = ?, move_in_ready_reason = ?, "
                "needs_repair = ?, needs_repair_reason = ?, "
                "resale_ng = ?, resale_ng_reason = ?, resale_warnings = ? WHERE id = ?",
                (pt, 1 if is_bad else 0, reason or None,
                 1 if is_ready else 0, ready_reason or None,
                 1 if repair_needed else 0, repair_reason or None,
                 1 if ng else 0, ng_reason or None,
                 "|".join(warnings) if warnings else None, r["id"]),
            )
    click.echo(
        f"reclassified {len(rows)} properties: type={type_counts}, "
        f"dilapidated={dilap_count}, move_in_ready={ready_count}, needs_repair={repair_count}, "
        f"resale_ng={ng_count}, with_warnings={warn_count}"
    )


@cli.command()
@click.option("--limit", default=200, type=int, help="一度に見に行く最大件数")
def enrich(limit: int) -> None:
    """詳細ページから掲載開始日(情報公開日)を取得する。未取得の物件だけ1回だけ見に行く。"""
    from . import enrich as en
    db.init_db()
    with db.connect() as conn:
        st = en.enrich_missing(conn, limit=limit)
    click.echo(
        f"target={st['target']} 掲載日あり={st['found']} 日付なし={st['no_date']} 失敗={st['failed']}"
    )


@cli.command("purge")
@click.option("--apply", "do_apply", is_flag=True,
              help="実際に削除する (付けなければ件数を数えるだけの下見)")
@click.option("--yes", is_flag=True, help="確認の質問を省略する (自動実行用)")
@click.option("--price-max", default=purge_rules.PRICE_CUTOFF_YEN, type=int, show_default=True,
              help="この金額以上の物件を削除対象にする (円)")
@click.option("--include-rated", is_flag=True, help="星評価済みの物件も削除対象にする")
def purge_cmd(do_apply: bool, yes: bool, price_max: int, include_rated: bool) -> None:
    """土地だけの物件と300万円以上の物件をDBから削除する (既定は下見のみ)。"""
    db.init_db()  # 本番にテーブルが無い状態でも落ちないように
    keep_rated = not include_rated
    with db.connect() as conn:
        stats = purge_rules.count_targets(conn, price_cutoff=price_max, keep_rated=keep_rated)
        click.echo(purge_rules.render_report(stats, applied=False))
        if not do_apply:
            click.echo("\n※ まだ何も削除していません。実際に消すには --apply を付けてください。")
            return
        if stats["total"] == 0:
            click.echo("\n削除対象がありません。")
            return
        if not yes and not click.confirm(
            f"\n本当に {stats['total']} 件を削除しますか？ (元に戻せません)", default=False
        ):
            click.echo("中止しました。")
            return
        purge_rules.purge(conn, price_cutoff=price_max, keep_rated=keep_rated)
        click.echo(f"\n削除しました: 物件 {stats['total']} 件 + 関連データ")


@cli.command()
@click.option("--limit", default=50, type=int, help="一度に判定する最大件数")
def assess(limit: int) -> None:
    """再販目線の AI 構造化判定 (設備/ライフライン等を推定。既定は Gemini 無料枠)。"""
    from . import llm, resale_ai
    db.init_db()
    try:
        with db.connect() as conn:
            stats = resale_ai.assess_unassessed(conn, limit=limit)
    except llm.NoAPIKey as e:
        click.echo(f"スキップしました: {e}", err=True)
        return
    msg = f"target={stats['target']} assessed={stats['assessed']} failed={stats['failed']}"
    if stats.get("quota_stopped"):
        msg += " (無料枠を使い切ったため中断。残りは翌日の自動実行で続行します)"
    click.echo(msg)


@cli.group("launchd")
def launchd_grp() -> None:
    """launchd への登録/解除。"""


@launchd_grp.command("install")
def launchd_install() -> None:
    from . import scheduler
    scheduler.install()


@launchd_grp.command("uninstall")
def launchd_uninstall() -> None:
    from . import scheduler
    scheduler.uninstall()


@launchd_grp.command("status")
def launchd_status() -> None:
    from . import scheduler
    scheduler.status()


if __name__ == "__main__":
    cli()
