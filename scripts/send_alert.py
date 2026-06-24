#!/usr/bin/env python3
"""Send premarket radar alerts.

This module never trades and never places orders. It only sends a saved
Markdown report through best-effort local notification channels.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "watchlist.yaml"
SECRETS_ENV_PATH = ROOT / "config" / "secrets.env"


def load_local_env(path: Path = SECRETS_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


load_local_env()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_notification_config() -> dict:
    text = _read_text(CONFIG_PATH) if CONFIG_PATH.exists() else ""
    config = {
        "desktop_enabled": True,
        "email_enabled": False,
        "telegram_enabled": False,
        "pushplus_enabled": False,
        "serverchan_enabled": False,
        "email_to": "295765031@qq.com",
    }
    for line in text.splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in config:
            if value.lower() in {"true", "false"}:
                config[key] = value.lower() == "true"
            else:
                config[key] = value
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        config["telegram_enabled"] = True
    if os.environ.get("PUSHPLUS_TOKEN"):
        config["pushplus_enabled"] = True
    if os.environ.get("SERVERCHAN_SENDKEY"):
        config["serverchan_enabled"] = True
    if all(
        os.environ.get(name)
        for name in ["PREMARKET_SMTP_HOST", "PREMARKET_SMTP_USER", "PREMARKET_SMTP_PASSWORD"]
    ):
        config["email_enabled"] = True
    return config


def report_summary(report_text: str) -> tuple[str, str]:
    lines = [line.strip() for line in report_text.splitlines() if line.strip()]
    title = "北斗全时段异动雷达"
    body_parts: list[str] = []
    for line in lines:
        if line.startswith("今天盘前最值得盯的是") or line.startswith("当前"):
            body_parts.append(line)
        if line.startswith("【1】"):
            body_parts.append(line.replace("【1】", "1. "))
        if len(body_parts) >= 2:
            break
    body = "\n".join(body_parts) if body_parts else "\n".join(lines[:4])
    return title, body[:900]


def send_desktop_notification(title: str, body: str) -> bool:
    """Try BurntToast, then msg.exe. Both are best-effort."""
    ps = (
        "$ErrorActionPreference='Stop';"
        "if (Get-Module -ListAvailable BurntToast) {"
        f"Import-Module BurntToast; New-BurntToastNotification -Text {title!r}, {body!r}; exit 0"
        "} else { exit 2 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    try:
        msg = f"{title}\n{body}"
        result = subprocess.run(
            ["msg.exe", "*", msg[:900]],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return result.returncode == 0
    except Exception:
        return False


def send_email(title: str, body: str, report_text: str, to_addr: str) -> bool:
    host = os.environ.get("PREMARKET_SMTP_HOST")
    user = os.environ.get("PREMARKET_SMTP_USER")
    password = os.environ.get("PREMARKET_SMTP_PASSWORD")
    from_addr = os.environ.get("PREMARKET_EMAIL_FROM", user or "")
    port = int(os.environ.get("PREMARKET_SMTP_PORT", "465"))
    to_addr = os.environ.get("PREMARKET_EMAIL_TO", to_addr)
    if not all([host, user, password, from_addr, to_addr]):
        return False

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body + "\n\n" + report_text)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except Exception:
        return False


def post_json(url: str, payload: dict, headers: dict | None = None) -> bool:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def send_telegram(title: str, body: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return post_json(url, {"chat_id": chat_id, "text": f"{title}\n\n{body}"})


def send_pushplus(title: str, body: str) -> bool:
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        return False
    return post_json("https://www.pushplus.plus/send", {"token": token, "title": title, "content": body})


def send_serverchan(title: str, body: str) -> bool:
    sendkey = os.environ.get("SERVERCHAN_SENDKEY")
    if not sendkey:
        return False
    return post_json(f"https://sctapi.ftqq.com/{sendkey}.send", {"title": title, "desp": body})


def send_alert(report_path: Path, force_all: bool = False) -> dict:
    config = load_notification_config()
    report_text = _read_text(report_path)
    title, body = report_summary(report_text)
    results: dict[str, bool] = {}

    if force_all or config.get("desktop_enabled"):
        results["desktop"] = send_desktop_notification(title, body)
    if force_all or config.get("email_enabled"):
        results["email"] = send_email(title, body, report_text, str(config.get("email_to", "")))
    if force_all or config.get("telegram_enabled"):
        results["telegram"] = send_telegram(title, body)
    if force_all or config.get("pushplus_enabled"):
        results["pushplus"] = send_pushplus(title, body)
    if force_all or config.get("serverchan_enabled"):
        results["serverchan"] = send_serverchan(title, body)

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a 北斗盘前异动雷达 report.")
    parser.add_argument("report", type=Path, help="Markdown report path")
    parser.add_argument("--all", action="store_true", help="Try all channels regardless of config switches")
    args = parser.parse_args(argv)

    results = send_alert(args.report, force_all=args.all)
    for channel, ok in results.items():
        print(f"{channel}: {'ok' if ok else 'skipped_or_failed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
