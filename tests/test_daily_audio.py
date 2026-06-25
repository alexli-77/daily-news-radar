from __future__ import annotations

from pathlib import Path

from scripts.build_daily_audio import (
    build_audio_items,
    build_script,
    get_feishu_tenant_access_token,
    is_low_quality_item,
    send_feishu_webhook,
    send_feishu_audio,
    speech_text,
    speech_friendly_text,
    title_for_audio,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.ok = True
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeFeishuSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/"):
            return FakeResponse({"StatusCode": 0, "StatusMessage": "success"})
        if url.endswith("/auth/v3/tenant_access_token/internal"):
            return FakeResponse({"code": 0, "tenant_access_token": "tenant-token"})
        if url.endswith("/im/v1/files"):
            return FakeResponse({"code": 0, "data": {"file_key": "file-key"}})
        if "/im/v1/messages" in url:
            return FakeResponse({"code": 0, "data": {"message_id": f"om_{len(self.calls)}"}})
        raise AssertionError(f"unexpected url: {url}")


def test_audio_item_filter_rejects_page_fallback_clickthroughs():
    item = {
        "title": "点击这里进入 / Click here to enter",
        "source": "Page Fallback",
        "score": 0.99,
    }

    assert is_low_quality_item(item)


def test_title_for_audio_prefers_chinese_side_of_bilingual_title():
    item = {"title": "Gemini 3.5 Flash 中电脑使用介绍 / Introducing computer use in Gemini 3.5 Flash"}

    assert title_for_audio(item) == "Gemini 3.5 Flash 中电脑使用介绍"


def test_build_audio_items_falls_back_when_brief_is_too_noisy():
    primary = {
        "items": [
            {"title": "点击这里进入 / Click here to enter", "source": "Page Fallback", "score": 1.0},
            {"title": "OpenAI 发布新的 Codex 工具", "source": "OpenAI Blog", "score": 0.9, "category": "official"},
        ]
    }
    fallback = {
        "items": [
            {"title_zh": "Google 发布新的 Gemini 工具能力", "source": "Google DeepMind", "ai_score": 0.8, "url": "https://example.com/gemini"},
            {"title_zh": "Hugging Face 更新模型微调流程", "source": "Hugging Face Blog", "ai_score": 0.78, "url": "https://example.com/hf"},
            {"title_zh": "Notion 接入 Cursor 编码智能体", "source": "Cursor Blog", "ai_score": 0.76, "url": "https://example.com/notion"},
        ]
    }

    items = build_audio_items(primary, fallback, max_items=4, min_items=4)

    assert [item.title for item in items] == [
        "OpenAI 发布新的 Codex 工具",
        "Google 发布新的 Gemini 工具能力",
        "Hugging Face 更新模型微调流程",
        "Notion 接入 Cursor 编码智能体",
    ]


def test_build_script_is_plain_chinese_speech():
    payload = {
        "items": [
            {"title": "OpenAI 发布新的 Codex 工具", "source": "OpenAI Blog", "score": 0.9, "category": "official"},
        ]
    }
    script = build_script(build_audio_items(payload, max_items=1), generated_at="2026-06-25T00:00:00Z")

    assert "人工智能热点分享" in script
    assert "1、" in script
    assert "OpenAI 发布新的 Codex 工具" in script
    assert "Open A I" not in script
    assert "Open A I" in speech_text(script)
    assert "它来自官方渠道" not in script
    assert "http" not in script


def test_speech_friendly_text_rewrites_common_english_tokens():
    text = speech_friendly_text("OpenAI 的 AI 推理如何解锁 LLM 知识，GPT-5.5 Instant 更新")

    assert "人工智能" in text
    assert "大语言模型" in text
    assert "G P T 五点五" in text
    assert "Open A I" in text


def test_feishu_token_response_is_validated():
    session = FakeFeishuSession()

    token = get_feishu_tenant_access_token(app_id="app", app_secret="secret", session=session)

    assert token == "tenant-token"
    assert session.calls[0][1]["json"] == {"app_id": "app", "app_secret": "secret"}


def test_send_feishu_audio_uploads_file_and_sends_text(tmp_path: Path):
    audio_path = tmp_path / "brief.mp3"
    audio_path.write_bytes(b"fake mp3")
    session = FakeFeishuSession()

    result = send_feishu_audio(
        app_id="app",
        app_secret="secret",
        chat_id="oc_chat",
        audio_path=audio_path,
        digest_text="文字版摘要",
        session=session,
    )

    assert result["file_key"] == "file-key"
    assert result["file_message_id"] == "om_3"
    assert result["text_message_ids"] == ["om_4"]
    assert session.calls[2][1]["json"]["msg_type"] == "file"
    assert session.calls[3][1]["json"]["msg_type"] == "text"


def test_send_feishu_webhook_posts_text_with_audio_and_urls():
    session = FakeFeishuSession()

    result = send_feishu_webhook(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        digest_text="播报稿\n\n原文：https://example.com/news",
        audio_url="https://example.com/audio.mp3",
        session=session,
    )

    assert result == {"status": "ok", "messages": 1}
    payload = session.calls[0][1]["json"]
    assert payload["msg_type"] == "text"
    assert "https://example.com/audio.mp3" in payload["content"]["text"]
    assert "https://example.com/news" in payload["content"]["text"]
