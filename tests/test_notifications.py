from __future__ import annotations

import urllib.parse

from cross_etf_scout.notifications import load_notification_config
from cross_etf_scout.notifications import send_workwechat_text
from cross_etf_scout.notifications import send_telegram_message
from cross_etf_scout.notifications import TelegramConfig


def test_load_notification_config_reads_telegram_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=file-token\n"
        "TELEGRAM_CHAT_ID=file-chat\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
notifications:
  telegram:
    enabled: true
    env_file: "{env_path}"
    bot_token_env: "TELEGRAM_BOT_TOKEN"
    chat_id_env: "TELEGRAM_CHAT_ID"
""",
        encoding="utf-8",
    )

    config = load_notification_config(config_path)

    assert config.telegram.enabled is True
    assert config.telegram.bot_token == "file-token"
    assert config.telegram.chat_id == "file-chat"


def test_load_notification_config_reads_workwechat_env_file(tmp_path, monkeypatch):
    for key in ("WORKWECHAT_CORP_ID", "WORKWECHAT_CORP_SECRET", "WORKWECHAT_AGENT_ID"):
        monkeypatch.delenv(key, raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "WORKWECHAT_CORP_ID=file-corp\n"
        "WORKWECHAT_CORP_SECRET=file-secret\n"
        "WORKWECHAT_AGENT_ID=file-agent\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
notifications:
  workwechat:
    enabled: true
    env_file: "{env_path}"
    corp_id_env: "WORKWECHAT_CORP_ID"
    corp_secret_env: "WORKWECHAT_CORP_SECRET"
    agent_id_env: "WORKWECHAT_AGENT_ID"
    department_ids: ["3"]
""",
        encoding="utf-8",
    )

    config = load_notification_config(config_path)

    assert config.workwechat.enabled is True
    assert config.workwechat.corp_id == "file-corp"
    assert config.workwechat.corp_secret == "file-secret"
    assert config.workwechat.agent_id == "file-agent"
    assert config.workwechat.department_ids == ["3"]


def test_load_notification_config_prefers_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat")

    env_path = tmp_path / ".env"
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=file-token\n"
        "TELEGRAM_CHAT_ID=file-chat\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
notifications:
  telegram:
    enabled: true
    env_file: "{env_path}"
""",
        encoding="utf-8",
    )

    config = load_notification_config(config_path)

    assert config.telegram.bot_token == "env-token"
    assert config.telegram.chat_id == "env-chat"


def test_send_telegram_message_splits_long_text_and_omits_blank_parse_mode(monkeypatch):
    payloads = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        payloads.append(urllib.parse.parse_qs(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    config = TelegramConfig(enabled=True, bot_token="token", chat_id="chat")

    assert send_telegram_message("line\n" * 1000, config) is True
    assert len(payloads) == 2
    assert "parse_mode" not in payloads[0]
    assert all(len(payload["text"][0]) <= 3900 for payload in payloads)


def test_send_workwechat_text_uses_official_api(monkeypatch):
    requests = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        url = request.full_url
        requests.append(request)
        if "gettoken" in url:
            return FakeResponse(b'{"errcode":0,"access_token":"token"}')
        return FakeResponse(b'{"errcode":0,"errmsg":"ok"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = load_notification_config_from_text(
        """
notifications:
  workwechat:
    enabled: true
    corp_id: "corp"
    corp_secret: "secret"
    agent_id: "agent"
    department_ids: ["3"]
"""
    ).workwechat

    assert send_workwechat_text("hello", config) is True
    assert len(requests) == 2
    payload = urllib.parse.unquote(requests[1].data.decode("utf-8"))
    assert '"toparty": "3"' in payload
    assert '"content": "hello"' in payload


def test_send_workwechat_text_defaults_to_all_users_when_no_recipient(monkeypatch):
    requests = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        requests.append(request)
        if "gettoken" in request.full_url:
            return FakeResponse(b'{"errcode":0,"access_token":"token"}')
        return FakeResponse(b'{"errcode":0,"errmsg":"ok"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = load_notification_config_from_text(
        """
notifications:
  workwechat:
    enabled: true
    corp_id: "corp"
    corp_secret: "secret"
    agent_id: "agent"
"""
    ).workwechat

    assert send_workwechat_text("hello", config) is True
    payload = urllib.parse.unquote(requests[1].data.decode("utf-8"))
    assert '"touser": "@all"' in payload
    assert "toparty" not in payload


def test_send_workwechat_text_splits_long_text(monkeypatch):
    requests = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    def fake_urlopen(request, timeout):
        requests.append(request)
        if "gettoken" in request.full_url:
            return FakeResponse(b'{"errcode":0,"access_token":"token"}')
        return FakeResponse(b'{"errcode":0,"errmsg":"ok"}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = load_notification_config_from_text(
        """
notifications:
  workwechat:
    enabled: true
    corp_id: "corp"
    corp_secret: "secret"
    agent_id: "agent"
"""
    ).workwechat

    assert send_workwechat_text("line\n" * 1000, config) is True

    send_requests = [request for request in requests if "message/send" in request.full_url]
    assert len(send_requests) == 3
    for request in send_requests:
        payload = urllib.parse.unquote(request.data.decode("utf-8"))
        assert len(payload) <= 2600


def load_notification_config_from_text(text, tmp_path=None):
    from pathlib import Path
    import tempfile

    if tmp_path is None:
        temp_dir = tempfile.TemporaryDirectory()
        path = Path(temp_dir.name) / "config.yaml"
        path.write_text(text, encoding="utf-8")
        config = load_notification_config(path)
        temp_dir.cleanup()
        return config
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_notification_config(path)
