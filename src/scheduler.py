"""Mac 側の定期実行 (launchd)。

役割 (2026-09-22〜):
  アットホーム空き家バンク系 (48自治体) は、アットホームが海外IPを 403 で遮断するため
  GitHub Actions (米国) から取れない。**日本国内にある Mac から毎朝収集して本番DB
  (Turso) に直接書き込む**。GitHub 側はそれ以外の収集元を従来どおり担当する。

  接続情報は .env (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN) から読む。
  launchd は .env を自動では読まないが、src/cli.py が起動時に load_dotenv() するので
  WorkingDirectory をプロジェクトに向けておけば良い。

スケジュール:
  毎日 06:15 JST (GitHub 側の 06:00 JST と同じ時間帯に揃える)。
  Mac がスリープ中なら、次に起きたときに launchd がまとめて1回実行する。

コマンド:
  trade launchd install   … 登録 (以後は毎朝自動)
  trade launchd status    … 登録状況と直近ログ
  trade launchd run-now   … 今すぐ1回実行 (動作確認用)
  trade launchd uninstall … 解除
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL_ATHOME = "com.trade.scrape-athome"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PLIST_DIR = PROJECT_ROOT / "launchd"
LOG_DIR = PROJECT_ROOT / "logs"
RUN_HOUR, RUN_MINUTE = 6, 15


def _python_path() -> str:
    venv = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv if venv.exists() else sys.executable)


def _plist_xml(label: str, args: list[str], *, hour: int, minute: int) -> str:
    program_args = "\n".join(f"        <string>{a}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_ROOT}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{LOG_DIR}/{label}.out.log</string>
    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/{label}.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""


def _write_plist() -> Path:
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    plist = PLIST_DIR / f"{LABEL_ATHOME}.plist"
    plist.write_text(_plist_xml(
        LABEL_ATHOME,
        args=[_python_path(), "-m", "src.cli", "scrape", "--group", "athome"],
        hour=RUN_HOUR, minute=RUN_MINUTE,
    ))
    return plist


def _check_env() -> list[str]:
    """本番DBに書くために必要な設定が .env にあるか。無ければ足りない名前を返す。"""
    from dotenv import dotenv_values
    env = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    return [k for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN") if not env.get(k)]


def install() -> None:
    missing = _check_env()
    if missing:
        print("⚠️ .env に本番DBの接続情報がありません:", ", ".join(missing))
        print("   config/.env.example を参考に、プロジェクト直下の .env に書いてから再実行してください。")
        print("   (値は GitHub の Settings → Secrets に登録してあるものと同じです)")
        sys.exit(1)
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    src = _write_plist()
    dst = LAUNCH_AGENTS / src.name
    dst.write_bytes(src.read_bytes())
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL_ATHOME}"],
                   check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst)], check=True)
    print(f"✅ 登録しました: 毎日 {RUN_HOUR:02d}:{RUN_MINUTE:02d} にアットホーム系48自治体を収集して本番に書き込みます")
    print(f"   ログ: {LOG_DIR}/{LABEL_ATHOME}.out.log")


def uninstall() -> None:
    uid = os.getuid()
    dst = LAUNCH_AGENTS / f"{LABEL_ATHOME}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL_ATHOME}"],
                   check=False, capture_output=True)
    if dst.exists():
        dst.unlink()
    print("解除しました")


def run_now() -> None:
    """登録済みのジョブを今すぐ1回起動する (動作確認用)。"""
    uid = os.getuid()
    r = subprocess.run(["launchctl", "kickstart", f"gui/{uid}/{LABEL_ATHOME}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("起動できませんでした (未登録?):", r.stderr.strip())
        sys.exit(1)
    print(f"起動しました。数分後に {LOG_DIR}/{LABEL_ATHOME}.out.log を確認してください。")


def status() -> None:
    uid = os.getuid()
    r = subprocess.run(["launchctl", "print", f"gui/{uid}/{LABEL_ATHOME}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("未登録です。`trade launchd install` で登録できます。")
        return
    state = next((ln.strip() for ln in r.stdout.splitlines() if "state =" in ln), "state = ?")
    last = next((ln.strip() for ln in r.stdout.splitlines() if "last exit code" in ln), "")
    print(f"登録済み: 毎日 {RUN_HOUR:02d}:{RUN_MINUTE:02d} / {state} / {last}")
    out = LOG_DIR / f"{LABEL_ATHOME}.out.log"
    if out.exists():
        lines = out.read_text(encoding="utf-8", errors="ignore").splitlines()
        tail = [ln for ln in lines if "raw=" in ln or "sold:" in ln][-6:]
        print("直近の結果:")
        for ln in tail:
            print("  ", ln)
    else:
        print("まだ一度も実行されていません")
