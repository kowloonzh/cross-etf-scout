from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config/config.yaml")
TELEGRAM_CHUNK_SIZE = 3900
WORKWECHAT_CHUNK_SIZE = 1900


@dataclass(frozen=True)
class WorkWechatConfig:
    enabled: bool = False
    user_ids: list[str] = field(default_factory=list)
    department_ids: list[str] = field(default_factory=list)
    tag_ids: list[str] = field(default_factory=list)
    env_file: str = ".env"
    corp_id_env: str = "WORKWECHAT_CORP_ID"
    corp_secret_env: str = "WORKWECHAT_CORP_SECRET"
    agent_id_env: str = "WORKWECHAT_AGENT_ID"
    corp_id: str = ""
    corp_secret: str = field(default="", repr=False)
    agent_id: str = ""


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    env_file: str = ".env"
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    parse_mode: str = ""
    bot_token: str = field(default="", repr=False)
    chat_id: str = field(default="", repr=False)


@dataclass(frozen=True)
class NotificationConfig:
    workwechat: WorkWechatConfig
    telegram: TelegramConfig


def load_notification_config(path: str | Path = DEFAULT_CONFIG_PATH) -> NotificationConfig:
    config_path = Path(path)
    raw = _load_yaml(config_path)
    notifications = raw.get("notifications", {})

    workwechat_raw = notifications.get("workwechat", {})
    telegram_raw = notifications.get("telegram", {})
    workwechat_env_file = str(workwechat_raw.get("env_file", ".env"))
    workwechat_env_values = _load_env_file(workwechat_env_file)
    corp_id_env = str(workwechat_raw.get("corp_id_env", "WORKWECHAT_CORP_ID"))
    corp_secret_env = str(workwechat_raw.get("corp_secret_env", "WORKWECHAT_CORP_SECRET"))
    agent_id_env = str(workwechat_raw.get("agent_id_env", "WORKWECHAT_AGENT_ID"))
    env_file = str(telegram_raw.get("env_file", ".env"))
    env_values = _load_env_file(env_file)
    bot_token_env = str(telegram_raw.get("bot_token_env", "TELEGRAM_BOT_TOKEN"))
    chat_id_env = str(telegram_raw.get("chat_id_env", "TELEGRAM_CHAT_ID"))

    return NotificationConfig(
        workwechat=WorkWechatConfig(
            enabled=bool(workwechat_raw.get("enabled", False)),
            user_ids=_load_string_list(workwechat_raw.get("user_ids", [])),
            department_ids=_load_workwechat_department_ids(workwechat_raw),
            tag_ids=_load_string_list(workwechat_raw.get("tag_ids", [])),
            env_file=workwechat_env_file,
            corp_id_env=corp_id_env,
            corp_secret_env=corp_secret_env,
            agent_id_env=agent_id_env,
            corp_id=os.environ.get(
                corp_id_env,
                str(workwechat_raw.get("corp_id", "") or workwechat_env_values.get(corp_id_env, "")),
            ),
            corp_secret=os.environ.get(
                corp_secret_env,
                str(workwechat_raw.get("corp_secret", "") or workwechat_env_values.get(corp_secret_env, "")),
            ),
            agent_id=os.environ.get(
                agent_id_env,
                str(workwechat_raw.get("agent_id", "") or workwechat_env_values.get(agent_id_env, "")),
            ),
        ),
        telegram=TelegramConfig(
            enabled=bool(telegram_raw.get("enabled", False)),
            env_file=env_file,
            bot_token_env=bot_token_env,
            chat_id_env=chat_id_env,
            parse_mode=str(telegram_raw.get("parse_mode", "") or ""),
            bot_token=os.environ.get(bot_token_env, env_values.get(bot_token_env, "")),
            chat_id=os.environ.get(chat_id_env, env_values.get(chat_id_env, "")),
        ),
    )


def send_workwechat_text(message: str, config: WorkWechatConfig) -> bool:
    if not config.enabled:
        return False
    if not config.corp_id or not config.corp_secret or not config.agent_id:
        print("WorkWechat notification skipped: missing corp id, corp secret, or agent id")
        return False

    try:
        access_token = _get_workwechat_access_token(config)
        sent_count = 0
        for chunk in _split_text(message, WORKWECHAT_CHUNK_SIZE):
            result = _send_workwechat_text(access_token, chunk, config)
            if not isinstance(result, dict) or result.get("errcode", 0) != 0:
                print(f"WorkWechat result: {result}")
                return False
            sent_count += 1
        print(f"WorkWechat result: ok ({sent_count} message(s))")
        return True
    except Exception as exc:
        print(f"WorkWechat notification failed: {exc}")
        return False


def send_telegram_message(text: str, config: TelegramConfig) -> bool:
    if not config.enabled:
        return False
    if not config.bot_token or not config.chat_id:
        print("Telegram notification skipped: missing bot token or chat id")
        return False

    url = f"https://api.telegram.org/bot{urllib.parse.quote(config.bot_token, safe='')}/sendMessage"
    sent_count = 0
    for chunk in _split_text(text, TELEGRAM_CHUNK_SIZE):
        payload_data = {
            "chat_id": config.chat_id,
            "text": chunk,
            "disable_web_page_preview": "true",
        }
        if config.parse_mode:
            payload_data["parse_mode"] = config.parse_mode
        payload = urllib.parse.urlencode(payload_data).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
            sent_count += 1
        except Exception as exc:
            print(f"Telegram notification failed: {exc}")
            return False
    print(f"Telegram result: ok ({sent_count} message(s))")
    return True


def notify_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cross-etf-notify")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--channel", choices=["workwechat", "telegram"], required=True)
    parser.add_argument("--message", default="")
    parser.add_argument("--file", default="")
    args = parser.parse_args(argv)

    message = args.message
    if args.file:
        message = Path(args.file).read_text(encoding="utf-8")
    if not message:
        print("notification message is empty")
        return 1

    config = load_notification_config(args.config)
    if args.channel == "workwechat":
        return 0 if send_workwechat_text(message, config.workwechat) else 1
    return 0 if send_telegram_message(message, config.telegram) else 1


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _load_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    with env_path.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _get_workwechat_access_token(config: WorkWechatConfig) -> str:
    query = urllib.parse.urlencode(
        {
            "corpid": config.corp_id,
            "corpsecret": config.corp_secret,
        }
    )
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{query}"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errcode", 0) != 0:
        raise RuntimeError(f"gettoken failed: {payload}")
    access_token = str(payload.get("access_token", ""))
    if not access_token:
        raise RuntimeError("gettoken failed: missing access_token")
    return access_token


def _send_workwechat_text(
    access_token: str,
    message: str,
    config: WorkWechatConfig,
) -> dict[str, Any]:
    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/message/send?"
        + urllib.parse.urlencode({"access_token": access_token})
    )
    payload = {
        "msgtype": "text",
        "agentid": config.agent_id,
        "text": {"content": message},
        "safe": 0,
    }
    payload.update(_workwechat_recipient_payload(config))
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _workwechat_recipient_payload(config: WorkWechatConfig) -> dict[str, str]:
    payload: dict[str, str] = {}
    if config.user_ids:
        payload["touser"] = "|".join(config.user_ids)
    if config.department_ids:
        payload["toparty"] = "|".join(config.department_ids)
    if config.tag_ids:
        payload["totag"] = "|".join(config.tag_ids)
    if not payload:
        payload["touser"] = "@all"
    return payload


def _load_workwechat_department_ids(raw: dict[str, Any]) -> list[str]:
    if "department_ids" in raw:
        return _load_string_list(raw.get("department_ids"))
    if "department_id" in raw:
        return _load_string_list(raw.get("department_id"))
    return []


def _load_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split("|") if part.strip()]


def _split_text(text: str, chunk_size: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, chunk_size)
        if split_at <= 0:
            split_at = chunk_size
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


if __name__ == "__main__":
    raise SystemExit(notify_main())
