"""CLI: trade scrape | notify | web | db init | launchd ..."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from . import db, filter as flt, normalize
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
            stats = {"raw": 0, "new": 0, "updated": 0}
            for raw in scraper.fetch(client):
                stats["raw"] += 1
                listing = normalize.normalize(raw)
                _pid, is_new = db.upsert_listing(conn, listing)
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1
            summary[name] = stats
            log.info("%s: %s", name, stats)
    for name, s in summary.items():
        click.echo(f"{name}: raw={s['raw']} new={s['new']} updated={s['updated']}")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Discord に送らず stdout に出すだけ")
@click.option("--use-distance-matrix", is_flag=True, help="境界府県を Distance Matrix で詰める")
def notify(dry_run: bool, use_distance_matrix: bool) -> None:
    """未通知 & filter pass の物件を Discord に通知。"""
    from . import notifier_discord as nd
    cfg = flt.FilterConfig.load()
    with db.connect() as conn:
        stats = nd.notify(conn, cfg, dry_run=dry_run, use_distance_matrix=use_distance_matrix)
    click.echo(f"scanned={stats['scanned']} passed={stats['passed']} sent={stats['sent']}")


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
    """AI で未スコア物件をスコア付け (preferences.yaml を基準に Claude 採点)。"""
    from . import scorer
    cfg = scorer.PreferenceConfig.load()
    with db.connect() as conn:
        stats = scorer.score_unscored(conn, cfg, limit=limit)
    click.echo(f"target={stats['target']} scored={stats['scored']} failed={stats['failed']}")


@cli.command()
def reclassify() -> None:
    """既存物件の property_type を title+body から再分類 (タイプフィルタ追加時のバックフィル)。"""
    db.init_db()  # ALTER TABLE が必要なら自動実行
    with db.connect() as conn:
        rows = conn.execute("SELECT id, title, body, property_type FROM properties").fetchall()
        counts: dict[str, int] = {}
        for r in rows:
            pt = normalize.classify_property_type(r["title"], r["body"])
            counts[pt] = counts.get(pt, 0) + 1
            if pt != r["property_type"]:
                conn.execute(
                    "UPDATE properties SET property_type = ? WHERE id = ?",
                    (pt, r["id"]),
                )
    click.echo(f"reclassified {len(rows)} properties: {counts}")


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
