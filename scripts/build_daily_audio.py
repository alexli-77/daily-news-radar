from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


DEFAULT_VOICE = "zh-CN-YunyangNeural"
DEFAULT_DATE_TIMEZONE = "Asia/Shanghai"
DEFAULT_FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
BAD_TITLE_PATTERNS = (
    "click here",
    "click here to enter",
    "点击这里",
    "进入 / click",
    "untitled",
)
AI_SIGNAL_PATTERNS = (
    "ai",
    "人工智能",
    "大模型",
    "模型",
    "llm",
    "gpt",
    "claude",
    "gemini",
    "openai",
    "deepmind",
    "hugging face",
    "nvidia",
    "英伟达",
    "transformer",
    "微调",
    "推理",
    "训练",
    "智能体",
    "agent",
    "cursor",
    "算力",
    "芯片",
    "服务器",
    "语音",
    "tts",
    "生成",
)
SPEECH_REPLACEMENTS = (
    (r"\bMistral AI\b", "Mistral"),
    (r"\bNVIDIA\b", "英伟达"),
    (r"\bGoogle DeepMind\b", "谷歌 DeepMind"),
    (r"\bHugging Face\b", "Hugging Face"),
    (r"\bOpenAI\b", "Open A I"),
    (r"\bGitHub\b", "GitHub"),
    (r"\bTransformer\b", "Transformer"),
    (r"\bTTS\b", "语音合成"),
    (r"\bSDK\b", "S D K"),
    (r"\bConnectors\b", "连接器"),
)
SOURCE_ALIASES = {
    "Hugging Face Blog": "Hugging Face 博客",
    "Google DeepMind": "谷歌 DeepMind",
    "Google Research：Blog（网页）": "谷歌 Research 博客",
    "GitHub Changelog": "GitHub 更新日志",
    "Cursor Blog": "Cursor 博客",
    "The Decoder：AI News（RSS）": "The Decoder",
    "Mistral AI：News（网页）": "Mistral",
    "X：OpenAI (@OpenAI)": "OpenAI",
    "X：Perplexity (@perplexity_ai)": "Perplexity",
}


@dataclass(frozen=True)
class AudioItem:
    title: str
    source: str
    url: str
    score: float
    category: str
    reason: str
    source_count: int = 1


@dataclass(frozen=True)
class EditedBullet:
    section: str
    text: str
    item: AudioItem


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def title_for_audio(item: dict[str, Any]) -> str:
    title = first_text(
        item.get("title_zh"),
        item.get("title_bilingual"),
        item.get("title"),
        item.get("title_original"),
        item.get("primary_item", {}).get("title") if isinstance(item.get("primary_item"), dict) else "",
    )
    if " / " in title and re.search(r"[\u3400-\u9fff]", title.split(" / ", 1)[0]):
        title = title.split(" / ", 1)[0]
    return normalize_space(title)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def score_for_item(item: dict[str, Any]) -> float:
    for key in ("importance_score", "importance", "score", "ai_score"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def source_for_item(item: dict[str, Any]) -> str:
    source = first_text(item.get("source"), item.get("source_name"), item.get("site_name"), "未知来源")
    return SOURCE_ALIASES.get(source, source)


def is_low_quality_item(item: dict[str, Any]) -> bool:
    title = title_for_audio(item)
    source = source_for_item(item)
    haystack = f"{title} {source}".casefold()
    if not title or len(title) < 6:
        return True
    if any(pattern in haystack for pattern in BAD_TITLE_PATTERNS):
        return True
    if "page fallback" in haystack:
        return True
    if title.startswith(("http://", "https://")):
        return True
    return False


def has_ai_signal(item: dict[str, Any]) -> bool:
    title = title_for_audio(item)
    haystack = " ".join(
        [
            title,
            first_text(item.get("title_original"), item.get("title_en"), item.get("title_bilingual")),
            source_for_item(item),
            " ".join(str(signal) for signal in item.get("ai_signals", []) if isinstance(signal, str)),
            first_text(item.get("ai_relevance_reason")),
        ]
    ).casefold()
    return any(pattern in haystack for pattern in AI_SIGNAL_PATTERNS)


def reason_for_item(item: dict[str, Any]) -> str:
    source_count = int(item.get("source_count") or item.get("item_count") or 1)
    category = first_text(item.get("category"))
    ai_reason = first_text(item.get("ai_relevance_reason"))
    if source_count >= 2:
        return "它被多个来源同时提到，说明这不是孤立信号。"
    if category == "official":
        return "它来自官方渠道，适合优先确认产品和能力变化。"
    if category == "industry":
        return "它反映了产业侧正在发生的变化，值得留意后续影响。"
    if ai_reason:
        return normalize_space(ai_reason).rstrip("。.") + "。"
    return "它的相关性和时效性都比较高，适合作为今天的重点观察。"


def speech_friendly_text(text: str) -> str:
    result = text
    for pattern, replacement in SPEECH_REPLACEMENTS:
        result = re.sub(pattern, replacement, result)
    result = re.sub(r"(?<![A-Za-z])Gemini\s+3\.5\s+Flash(?![A-Za-z])", "Gemini 三点五 Flash", result)
    result = re.sub(r"(?<![A-Za-z])GPT-5\.5(?![A-Za-z])", "G P T 五点五", result)
    result = re.sub(r"(?<![A-Za-z])GPT(?![A-Za-z])", "G P T", result)
    result = re.sub(r"(?<![A-Za-z])LLM(?![A-Za-z])", "大语言模型", result)
    result = re.sub(r"(?<![A-Za-z])AI(?![A-Za-z])", "人工智能", result)
    result = re.sub(r"^使用\s+", "", result)
    return normalize_space(result)


def section_for_item(item: AudioItem) -> str:
    text = f"{item.title} {item.source} {item.category}".casefold()
    if any(term in text for term in ("cursor", "notion", "github", "开发者", "编码", "微调", "transformer", "hugging face")):
        return "二、开发者工具与工程更新"
    if any(term in text for term in ("服务器", "芯片", "算力", "散热", "nvidia", "英伟达", "gpu")):
        return "三、产业与算力动态"
    return "一、模型与产品更新"


def bullet_for_item(item: AudioItem) -> str:
    title = speech_friendly_text(item.title)
    compact = title.rstrip("。")
    lower = title.casefold()
    source = speech_friendly_text(item.source)
    if "gemini" in lower and ("电脑使用" in title or "计算机使用" in title):
        return "谷歌 DeepMind 介绍 Gemini 三点五 Flash 的电脑操作能力，重点是让模型直接使用网页和软件，智能体继续从聊天走向执行。"
    if "nemo" in lower and "automodel" in lower and "微调" in title:
        return "英伟达和 Hugging Face 更新 NeMo AutoModel 微调流程，开发者可以用更少代码加速 Transformer 模型训练。"
    if "g p t 五点五" in title.casefold() or "instant" in lower:
        return "Open A I 更新 G P T 五点五 Instant，对话体验强调更快、更有趣，属于模型产品体验优化。"
    if "思考即回忆" in title or "参数化知识" in title:
        return "谷歌研究讨论推理如何调动大语言模型内部知识，重点是提升模型回答复杂问题时的可靠性。"
    if "figma" in lower and "config" in lower:
        return "Figma 在 Config 二零二六强调人类判断，同时把部分画布人工智能能力交给第三方模型，设计工具的人工智能分工更清晰。"
    if "mistral" in lower and ("connector" in lower or "连接器" in title):
        return "Mistral 为连接器增加安全和可控能力，重点是让企业接入数据源时更好管理权限和风险。"
    if "微调" in title:
        return f"{compact}，重点是提升模型微调效率，属于开发者训练流程更新。"
    if "电脑使用" in title or "计算机使用" in title:
        return f"{compact}，指向模型直接操作软件和网页的能力，是智能体产品化的重要方向。"
    if "编码智能体" in title or "cursor" in lower:
        return f"{compact}，说明人工智能编码能力正在嵌入协作和生产力工具。"
    if "工程岗位" in title:
        return f"{compact}，反映人工智能对招聘和岗位结构的影响仍在重新定价。"
    if any(term in title for term in ("服务器", "芯片", "算力", "散热")):
        return f"{compact}，属于人工智能基础设施和算力成本相关信号。"
    if item.source_count >= 2:
        return f"{compact}，多个来源同时出现，热度较高。"
    return f"{compact}，来自 {source}。"


def dedupe_key(item: dict[str, Any]) -> str:
    key = title_for_audio(item).casefold()
    semantic = key.replace(" ", "")
    if "gemini" in semantic and ("电脑使用" in semantic or "计算机使用" in semantic or "computeruse" in semantic):
        return "gemini计算机使用"
    if "nemo" in semantic and "automodel" in semantic and "微调" in semantic:
        return "nemoautomodel微调"
    replacements = {
        "电脑使用": "计算机使用",
        "computer use": "计算机使用",
        "中的": "",
        "中": "",
        "的": "",
        "介绍": "",
        "发布": "",
        "推出": "",
    }
    for old, new in replacements.items():
        key = key.replace(old, new)
    key = re.sub(r"[\W_]+", "", key)
    return key


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "items_ai", "stories"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def build_audio_items(
    primary_payload: dict[str, Any],
    fallback_payload: dict[str, Any] | None = None,
    *,
    max_items: int = 6,
    min_items: int = 4,
) -> list[AudioItem]:
    candidates = [
        item for item in extract_items(primary_payload)
        if not is_low_quality_item(item) and has_ai_signal(item)
    ]
    if fallback_payload and len(candidates) < min_items:
        seen = {first_text(item.get("url"), title_for_audio(item)) for item in candidates}
        for item in extract_items(fallback_payload):
            key = first_text(item.get("url"), title_for_audio(item))
            if key in seen or is_low_quality_item(item) or not has_ai_signal(item):
                continue
            candidates.append(item)
            seen.add(key)

    candidates.sort(key=score_for_item, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in candidates:
        key = dedupe_key(item)
        if key in seen_titles:
            continue
        selected.append(item)
        seen_titles.add(key)
        if len(selected) >= max_items:
            break
    return [
        AudioItem(
            title=title_for_audio(item),
            source=source_for_item(item),
            url=first_text(item.get("url"), item.get("primary_url")),
            score=score_for_item(item),
            category=first_text(item.get("category"), "news"),
            reason=reason_for_item(item),
            source_count=int(item.get("source_count") or item.get("item_count") or 1),
        )
        for item in selected
    ]


def parse_generated_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def chinese_date(now: datetime | None = None, *, timezone_name: str = DEFAULT_DATE_TIMEZONE) -> str:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(timezone_name))
    return f"{local.year}年{local.month}月{local.day}日"


def edit_bullets(items: list[AudioItem]) -> list[EditedBullet]:
    return [
        EditedBullet(section=section_for_item(item), text=bullet_for_item(item), item=item)
        for item in items
    ]


def build_script(
    items: list[AudioItem],
    *,
    generated_at: str = "",
    title: str = "AI 新闻雷达",
    date_timezone: str = DEFAULT_DATE_TIMEZONE,
) -> str:
    report_date = chinese_date(parse_generated_at(generated_at), timezone_name=date_timezone)
    if not items:
        return f"{report_date}人工智能热点分享\n一、人工智能热点\n1、今天暂时没有筛出足够可靠的人工智能新闻信号。"

    lines = [f"{report_date}人工智能热点分享"]
    grouped: dict[str, list[EditedBullet]] = {}
    for bullet in edit_bullets(items):
        grouped.setdefault(bullet.section, []).append(bullet)

    section_order = ["一、模型与产品更新", "二、开发者工具与工程更新", "三、产业与算力动态"]
    for section in section_order:
        bullets = grouped.get(section, [])
        if not bullets:
            continue
        lines.append(section)
        for index, bullet in enumerate(bullets, start=1):
            lines.append(f"{index}、{bullet.text}")

    return "\n".join(lines)


def build_text_digest(items: list[AudioItem], script: str) -> str:
    lines = ["# AI 新闻雷达音频简报", "", "## 播报稿", "", script, "", "## 原始链接"]
    for index, item in enumerate(items, start=1):
        link = f" - {item.url}" if item.url else ""
        lines.append(f"{index}. {item.title}（{item.source}）{link}")
    return "\n".join(lines).strip() + "\n"


def speech_text(script: str) -> str:
    text = speech_friendly_text(re.sub(r"https?://\S+", "", script))
    text = re.sub(r"[#*_`<>\[\]()]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def synthesize_edge_tts(text: str, output_path: Path, *, voice: str, rate: str, pitch: str) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed. Run: pip install -r requirements-audio.txt") from exc

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(output_path))


def send_discord_audio(
    *,
    channel_id: str,
    bot_token: str,
    audio_path: Path,
    content: str,
    thread_name: str,
    thread_text: str,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bot {bot_token}"}
    with audio_path.open("rb") as audio_file:
        response = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers=headers,
            data={"payload_json": json.dumps({"content": content}, ensure_ascii=False)},
            files={"files[0]": (audio_path.name, audio_file, "audio/mpeg")},
            timeout=60,
        )
    response.raise_for_status()
    message = response.json()

    thread_response = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages/{message['id']}/threads",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": thread_name[:90], "auto_archive_duration": 1440},
        timeout=30,
    )
    thread_response.raise_for_status()
    thread = thread_response.json()

    for chunk in split_chunks(thread_text, 1800):
        text_response = requests.post(
            f"https://discord.com/api/v10/channels/{thread['id']}/messages",
            headers={**headers, "Content-Type": "application/json"},
            json={"content": chunk},
            timeout=30,
        )
        text_response.raise_for_status()

    return {"message_id": message["id"], "thread_id": thread["id"]}


def feishu_api_url(api_base: str, path: str) -> str:
    return f"{api_base.rstrip('/')}/{path.lstrip('/')}"


def require_feishu_ok(payload: dict[str, Any], *, action: str) -> dict[str, Any]:
    if payload.get("code") == 0:
        return payload.get("data") or {}
    raise RuntimeError(f"Feishu {action} failed: code={payload.get('code')} msg={payload.get('msg')}")


def get_feishu_tenant_access_token(
    *,
    app_id: str,
    app_secret: str,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    session: Any = requests,
) -> str:
    response = session.post(
        feishu_api_url(api_base, "/auth/v3/tenant_access_token/internal"),
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    data = require_feishu_ok(payload, action="tenant_access_token")
    token = first_text(data.get("tenant_access_token"), payload.get("tenant_access_token"))
    if not token:
        raise RuntimeError("Feishu tenant_access_token response did not include a token.")
    return token


def feishu_upload_file(
    *,
    tenant_access_token: str,
    file_path: Path,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    session: Any = requests,
) -> str:
    headers = {"Authorization": f"Bearer {tenant_access_token}"}
    with file_path.open("rb") as file_obj:
        response = session.post(
            feishu_api_url(api_base, "/im/v1/files"),
            headers=headers,
            data={"file_type": "stream", "file_name": file_path.name},
            files={"file": (file_path.name, file_obj, "audio/mpeg")},
            timeout=60,
        )
    response.raise_for_status()
    data = require_feishu_ok(response.json(), action="file upload")
    file_key = first_text(data.get("file_key"))
    if not file_key:
        raise RuntimeError("Feishu file upload response did not include file_key.")
    return file_key


def feishu_send_message(
    *,
    tenant_access_token: str,
    receive_id: str,
    msg_type: str,
    content: dict[str, Any],
    receive_id_type: str = "chat_id",
    api_base: str = DEFAULT_FEISHU_API_BASE,
    session: Any = requests,
) -> dict[str, Any]:
    response = session.post(
        feishu_api_url(api_base, f"/im/v1/messages?receive_id_type={receive_id_type}"),
        headers={
            "Authorization": f"Bearer {tenant_access_token}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
        timeout=30,
    )
    response.raise_for_status()
    return require_feishu_ok(response.json(), action=f"send {msg_type} message")


def send_feishu_audio(
    *,
    app_id: str,
    app_secret: str,
    chat_id: str,
    audio_path: Path,
    digest_text: str,
    api_base: str = DEFAULT_FEISHU_API_BASE,
    session: Any = requests,
) -> dict[str, Any]:
    tenant_access_token = get_feishu_tenant_access_token(
        app_id=app_id,
        app_secret=app_secret,
        api_base=api_base,
        session=session,
    )
    file_key = feishu_upload_file(
        tenant_access_token=tenant_access_token,
        file_path=audio_path,
        api_base=api_base,
        session=session,
    )
    file_message = feishu_send_message(
        tenant_access_token=tenant_access_token,
        receive_id=chat_id,
        msg_type="file",
        content={"file_key": file_key},
        api_base=api_base,
        session=session,
    )
    text = f"AI 新闻雷达音频简报已生成，音频文件见上方附件。\n\n{digest_text}"
    text_messages = []
    for chunk in split_chunks(text, 3000):
        text_messages.append(
            feishu_send_message(
                tenant_access_token=tenant_access_token,
                receive_id=chat_id,
                msg_type="text",
                content={"text": chunk},
                api_base=api_base,
                session=session,
            )
        )
    return {
        "file_key": file_key,
        "file_message_id": file_message.get("message_id"),
        "text_message_ids": [message.get("message_id") for message in text_messages],
    }


def split_chunks(text: str, max_len: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally deliver a human-like Chinese daily AI audio brief.")
    parser.add_argument("--input", default="data/daily-brief.json", help="Primary JSON input, usually data/daily-brief.json")
    parser.add_argument("--fallback", default="data/latest-24h.json", help="Fallback JSON input when the brief has too few clean items")
    parser.add_argument("--output-dir", default="out/daily-audio", help="Directory for generated audio and text")
    parser.add_argument("--max-items", type=int, default=6, help="Maximum stories to include")
    parser.add_argument("--min-items", type=int, default=4, help="Minimum clean brief stories before using fallback")
    parser.add_argument("--voice", default=os.getenv("AUDIO_TTS_VOICE", DEFAULT_VOICE), help="edge-tts voice name")
    parser.add_argument("--rate", default=os.getenv("AUDIO_TTS_RATE", "+0%"), help="edge-tts speaking rate, e.g. +8%")
    parser.add_argument("--pitch", default=os.getenv("AUDIO_TTS_PITCH", "+0Hz"), help="edge-tts pitch, e.g. -2Hz")
    parser.add_argument("--date-timezone", default=os.getenv("AUDIO_DATE_TIMEZONE", DEFAULT_DATE_TIMEZONE), help="Timezone used in the spoken date")
    parser.add_argument("--discord-channel-id", default=os.getenv("DISCORD_CHANNEL_ID", ""), help="Optional Discord channel ID")
    parser.add_argument("--feishu-chat-id", default=os.getenv("FEISHU_CHAT_ID", ""), help="Optional Feishu/Lark chat_id")
    parser.add_argument("--feishu-api-base", default=os.getenv("FEISHU_API_BASE", DEFAULT_FEISHU_API_BASE), help="Feishu/Lark OpenAPI base URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    primary_path = Path(args.input)
    fallback_path = Path(args.fallback)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    primary_payload = load_json(primary_path)
    fallback_payload = load_json(fallback_path) if fallback_path.exists() else None
    items = build_audio_items(primary_payload, fallback_payload, max_items=args.max_items, min_items=args.min_items)
    script = build_script(
        items,
        generated_at=first_text(primary_payload.get("generated_at")),
        date_timezone=args.date_timezone,
    )
    digest = build_text_digest(items, script)

    script_path = output_dir / "daily-ai-brief-script.txt"
    digest_path = output_dir / "daily-ai-brief.md"
    audio_path = output_dir / "daily-ai-brief.mp3"
    metadata_path = output_dir / "daily-ai-brief.json"

    script_path.write_text(script + "\n", encoding="utf-8")
    digest_path.write_text(digest, encoding="utf-8")
    asyncio.run(synthesize_edge_tts(speech_text(script), audio_path, voice=args.voice, rate=args.rate, pitch=args.pitch))

    result: dict[str, Any] = {
        "status": "ok",
        "audio": str(audio_path),
        "script": str(script_path),
        "digest": str(digest_path),
        "items": len(items),
        "voice": args.voice,
    }

    bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
    if args.discord_channel_id and bot_token:
        discord_result = send_discord_audio(
            channel_id=args.discord_channel_id,
            bot_token=bot_token,
            audio_path=audio_path,
            content="**AI 新闻雷达音频简报**\n中文人声音频版已生成，文字版在 thread 里。",
            thread_name="AI 新闻雷达音频简报",
            thread_text=digest,
        )
        result["discord"] = discord_result
    elif args.discord_channel_id:
        result["discord"] = {"status": "skipped", "reason": "DISCORD_BOT_TOKEN is not set"}

    feishu_app_id = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if args.feishu_chat_id and feishu_app_id and feishu_app_secret:
        result["feishu"] = send_feishu_audio(
            app_id=feishu_app_id,
            app_secret=feishu_app_secret,
            chat_id=args.feishu_chat_id,
            audio_path=audio_path,
            digest_text=digest,
            api_base=args.feishu_api_base,
        )
    elif args.feishu_chat_id:
        result["feishu"] = {"status": "skipped", "reason": "FEISHU_APP_ID or FEISHU_APP_SECRET is not set"}

    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
