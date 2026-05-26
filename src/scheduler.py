"""launchd plist 生成・install / uninstall."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LABEL_SCRAPE = "com.trade.scrape"
LABEL_NOTIFY = "com.trade.notify"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PLIST_DIR = PROJECT_ROOT / "launchd"


def _python_path() -> str:
    venv = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv if venv.exists() else sys.executable)


def _calendar_block(hour: int | None, minute: int | None) -> str:
    parts = []
    if hour is not None:
        parts.append(f"        <key>Hour</key><integer>{hour}</integer>")
    if minute is not None:
        parts.append(f"        <key>Minute</key><integer>{minute}</integer>")
    inner = "\n".join(parts)
    return (
        "    <key>StartCalendarInterval</key>\n"
        "    <dict>\n"
        f"{inner}\n"
        "    </dict>"
    )


def _plist_xml(
    label: str,
    args: list[str],
    *,
    interval_sec: int | None = None,
    calendar_hour: int | None = None,
    calendar_minute: int | None = None,
) -> str:
    program_args = "\n".join(f"        <string>{a}</string>" for a in args)
    if interval_sec is not None:
        schedule = f"    <key>StartInterval</key>\n    <integer>{interval_sec}</integer>"
    else:
        schedule = _calendar_block(calendar_hour, calendar_minute)
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
{schedule}
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{PROJECT_ROOT}/logs/{label}.out.log</string>
    <key>StandardErrorPath</key>
    <string>{PROJECT_ROOT}/logs/{label}.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
"""


def _write_plists() -> tuple[Path, Path]:
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    py = _python_path()

    # scrape: 15分間隔
    scrape_plist = PLIST_DIR / f"{LABEL_SCRAPE}.plist"
    scrape_plist.write_text(_plist_xml(
        LABEL_SCRAPE,
        args=[py, "-m", "src.cli", "scrape"],
        interval_sec=15 * 60,
    ))

    # notify: 毎時0分（Minute だけ指定）
    notify_plist = PLIST_DIR / f"{LABEL_NOTIFY}.plist"
    notify_plist.write_text(_plist_xml(
        LABEL_NOTIFY,
        args=[py, "-m", "src.cli", "notify"],
        calendar_minute=0,
    ))
    return scrape_plist, notify_plist


def install() -> None:
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    scrape_plist, notify_plist = _write_plists()
    uid = os.getuid()
    for src in (scrape_plist, notify_plist):
        dst = LAUNCH_AGENTS / src.name
        dst.write_bytes(src.read_bytes())
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{src.stem}"],
                       check=False, capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst)], check=True)
        print(f"loaded {dst}")


def uninstall() -> None:
    uid = os.getuid()
    for label in (LABEL_SCRAPE, LABEL_NOTIFY):
        dst = LAUNCH_AGENTS / f"{label}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                       check=False, capture_output=True)
        if dst.exists():
            dst.unlink()
            print(f"removed {dst}")


def status() -> None:
    uid = os.getuid()
    for label in (LABEL_SCRAPE, LABEL_NOTIFY):
        r = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if any(k in line for k in ("state =", "last exit code", "next firing", "interval")):
                    print(f"{label}: {line.strip()}")
        else:
            print(f"{label}: not loaded")
