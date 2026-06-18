import unittest
from unittest.mock import patch

from scripts.update_news import (
    build_agentmail_digest_payload,
    build_latest_payloads,
    dedupe_items_by_title_url,
    fetch_agentmail_digest,
    fetch_aihot,
    is_ai_related_record,
    is_hubtoday_generic_anchor_title,
    is_hubtoday_placeholder_title,
    maybe_fetch_agentmail_digest,
    maybe_fetch_x_api_updates,
    maybe_fix_mojibake,
    normalize_source_for_display,
    parse_ai_breakfast_items,
    parse_aihot_feed_items,
    parse_feed_entries_via_xml,
    parse_anthropic_news_items,
    parse_follow_builders_items,
    parse_openai_codex_changelog_items,
    redact_public_text,
)


class TopicFilterTests(unittest.TestCase):
    def test_accepts_ai_keyword(self):
        rec = {
            "site_id": "techurls",
            "site_name": "TechURLs",
            "source": "Hacker News",
            "title": "OpenAI releases new GPT model",
            "url": "https://example.com/ai",
        }
        self.assertTrue(is_ai_related_record(rec))

    def test_accepts_copilot_keyword(self):
        rec = {
            "site_id": "official_ai",
            "site_name": "Official AI Updates",
            "source": "GitHub Changelog",
            "title": "GitHub Copilot adds a new coding agent",
            "url": "https://example.com/copilot",
        }
        self.assertTrue(is_ai_related_record(rec))

    def test_accepts_robotics_keyword(self):
        rec = {
            "site_id": "newsnow",
            "site_name": "NewsNow",
            "source": "technology",
            "title": "Embodied robotics gets new funding",
            "url": "https://example.com/robotics",
        }
        self.assertTrue(is_ai_related_record(rec))

    def test_accepts_follow_builders_curated_feed(self):
        rec = {
            "site_id": "followbuilders",
            "site_name": "Follow Builders",
            "source": "Follow Builders · X · Andrej Karpathy",
            "title": "A terse but useful Codex builder note",
            "url": "https://x.com/karpathy/status/1",
        }
        self.assertTrue(is_ai_related_record(rec))

    def test_rejects_noise_topic(self):
        rec = {
            "site_id": "tophub",
            "site_name": "TopHub",
            "source": "微博热搜",
            "title": "明星八卦今日热搜",
            "url": "https://example.com/noise",
        }
        self.assertFalse(is_ai_related_record(rec))

    def test_rejects_commerce_noise(self):
        rec = {
            "site_id": "tophub",
            "site_name": "TopHub",
            "source": "淘宝 ‧ 天猫 · 热销总榜",
            "title": "白象拌面任选加码 券后¥29.96",
            "url": "https://example.com/shop",
        }
        self.assertFalse(is_ai_related_record(rec))

    def test_zeli_only_24h_hot(self):
        keep = {
            "site_id": "zeli",
            "site_name": "Zeli",
            "source": "Hacker News · 24h最热",
            "title": "AI Agent for code search",
            "url": "https://example.com/a",
        }
        drop = {
            "site_id": "zeli",
            "site_name": "Zeli",
            "source": "HN New",
            "title": "AI Agent for code search",
            "url": "https://example.com/b",
        }
        self.assertTrue(is_ai_related_record(keep))
        self.assertFalse(is_ai_related_record(drop))

    def test_buzzing_source_fallback_to_host(self):
        source = normalize_source_for_display("buzzing", "Buzzing", "https://news.ycombinator.com/item?id=1")
        self.assertEqual(source, "news.ycombinator.com")

    def test_fix_mojibake(self):
        raw = "è°å¨ç¼åä»£ç "
        self.assertEqual(maybe_fix_mojibake(raw), "谁在编写代码")

    def test_parse_feed_entries_via_xml(self):
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss><channel>
<item><title>A</title><link>https://x/a</link><pubDate>2026-02-20</pubDate></item>
</channel></rss>"""
        items = parse_feed_entries_via_xml(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "A")

    def test_parse_atom_feed_entries_via_xml(self):
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>A</title><link href="https://x/a" /><updated>2026-02-20</updated></entry>
</feed>"""
        items = parse_feed_entries_via_xml(xml)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "A")
        self.assertEqual(items[0]["link"], "https://x/a")

    def test_parse_anthropic_news_items(self):
        html = """
        <a href="/news/claude-opus-4-7">
          <time>Apr 16, 2026</time>
          <h2>Introducing Claude Opus 4.7</h2>
        </a>
        <a href="/news">News</a>
        """
        items = parse_anthropic_news_items(html, now=None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "Anthropic News")
        self.assertEqual(items[0].title, "Introducing Claude Opus 4.7")
        self.assertEqual(items[0].url, "https://www.anthropic.com/news/claude-opus-4-7")

    def test_parse_openai_codex_changelog_items(self):
        html = """
        <div id="codex-changelog-content">
          <li id="codex-2026-05-01">
            <time>2026-05-01</time>
            <h3><span>Codex app adds workspace companions</span></h3>
          </li>
        </div>
        """
        items = parse_openai_codex_changelog_items(html, now=None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "OpenAI Codex Changelog")
        self.assertEqual(items[0].title, "Codex app adds workspace companions")
        self.assertEqual(items[0].url, "https://developers.openai.com/codex/changelog#codex-2026-05-01")

    def test_parse_ai_breakfast_items(self):
        markdown = """
        [May 1, 2026 • 4 min read ### **Anthropic update lands** AI Breakfast](https://aibreakfast.beehiiv.com/p/anthropic-update-lands)
        [Apr 29, 2026 • 5 min read ### **OpenAI ships a model update** AI Breakfast](https://aibreakfast.beehiiv.com/p/openai-ships-model-update)
        """
        items = parse_ai_breakfast_items(markdown, now=None)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "AI Breakfast")
        self.assertEqual(items[0].title, "Anthropic update lands")
        self.assertEqual(items[0].url, "https://aibreakfast.beehiiv.com/p/anthropic-update-lands")

    def test_parse_aihot_feed_items(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<rss><channel><title>AI HOT — 精选</title>
<item>
<title>OpenAI ships a new Codex feature</title>
<link>https://example.com/codex</link>
<pubDate>Mon, 11 May 2026 02:05:04 GMT</pubDate>
<author>noreply@aihot.virxact.com (X：Builder)</author>
</item>
</channel></rss>""".encode("utf-8")
        items = parse_aihot_feed_items(xml, now=None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].site_id, "aihot")
        self.assertEqual(items[0].site_name, "AI HOT")
        self.assertEqual(items[0].title, "OpenAI ships a new Codex feature")
        self.assertEqual(items[0].url, "https://example.com/codex")

    def test_fetch_aihot_uses_fallback_when_primary_has_no_items(self):
        empty_xml = b"<?xml version='1.0'?><rss><channel><title>AI HOT</title></channel></rss>"
        fallback_xml = """<?xml version='1.0' encoding='UTF-8'?>
<rss><channel><title>AI HOT — 精选</title>
<item>
<title>Fallback AI HOT item</title>
<link>https://example.com/fallback</link>
<pubDate>Mon, 11 May 2026 04:53:06 GMT</pubDate>
</item>
</channel></rss>""".encode("utf-8")

        class FakeResponse:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                return None

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(url)
                return FakeResponse(empty_xml if len(self.calls) == 1 else fallback_xml)

        session = FakeSession()
        items = fetch_aihot(session, now=None)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Fallback AI HOT item")
        self.assertEqual(items[0].meta["feed_url"], session.calls[1])

    def test_parse_follow_builders_items(self):
        feeds = {
            "x": {
                "x": [
                    {
                        "name": "Andrej Karpathy",
                        "handle": "karpathy",
                        "tweets": [
                            {
                                "text": "LLM notes from the field",
                                "createdAt": "2026-05-02T06:21:22.000Z",
                                "url": "https://x.com/karpathy/status/1",
                            }
                        ],
                    }
                ]
            },
            "blogs": {
                "generatedAt": "2026-05-02T07:41:11.599Z",
                "blogs": [
                    {
                        "name": "Anthropic Engineering",
                        "title": "A Claude Code postmortem",
                        "url": "https://www.anthropic.com/engineering/postmortem",
                        "publishedAt": None,
                    }
                ],
            },
            "podcasts": {
                "podcasts": [
                    {
                        "name": "No Priors",
                        "title": "Inference cloud interview",
                        "url": "https://www.youtube.com/watch?v=abc",
                        "publishedAt": "2026-05-01T19:34:00.000Z",
                    }
                ]
            },
        }
        items = parse_follow_builders_items(feeds, now=None)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].site_id, "followbuilders")
        self.assertEqual(items[0].source, "Follow Builders · X · Andrej Karpathy")
        self.assertEqual(items[1].source, "Follow Builders · Blog · Anthropic Engineering")
        self.assertEqual(items[2].source, "Follow Builders · Podcast · No Priors")

    def test_hubtoday_placeholder_title(self):
        self.assertTrue(is_hubtoday_placeholder_title("详情见官方介绍(AI资讯)"))
        self.assertTrue(is_hubtoday_placeholder_title("查看详情"))
        self.assertFalse(is_hubtoday_placeholder_title("OpenAI 发布 GPT-5o"))
        self.assertTrue(is_hubtoday_generic_anchor_title("论文已公开(AI资讯)"))
        self.assertFalse(is_hubtoday_generic_anchor_title("Anthropic禁止第三方调用订阅。"))

    def test_dedupe_items_by_title_url_latest(self):
        items = [
            {
                "id": "1",
                "title": "Same",
                "title_original": "Same",
                "url": "https://example.com/a",
                "published_at": "2026-02-20T00:00:00Z",
            },
            {
                "id": "2",
                "title": "Same",
                "title_original": "Same",
                "url": "https://example.com/a",
                "published_at": "2026-02-20T01:00:00Z",
            },
        ]
        out = dedupe_items_by_title_url(items, random_pick=False)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "2")

    def test_rejects_broad_agent_noise_without_ai_context(self):
        rec = {
            "site_id": "buzzing",
            "site_name": "Buzzing",
            "source": "github.com",
            "title": "New travel agent marketplace launches in Europe",
            "url": "https://example.com/travel-agent",
        }
        self.assertFalse(is_ai_related_record(rec))

    def test_accepts_chinese_model_news_after_noise_tightening(self):
        rec = {
            "site_id": "tophub",
            "site_name": "TopHub",
            "source": "机器之心",
            "title": "新一代推理模型刷新多模态数学基准",
            "url": "https://example.com/reasoning-model",
        }
        self.assertTrue(is_ai_related_record(rec))

    def test_redacts_email_like_public_text(self):
        self.assertEqual(redact_public_text("Contact editor@example.com for access"), "Contact [redacted-email] for access")

    def test_build_latest_payloads_keeps_initial_payload_slim(self):
        latest_payload = {
            "generated_at": "2026-05-03T00:00:00Z",
            "window_hours": 24,
            "total_items": 1,
            "total_items_raw": 3,
            "total_items_all_mode": 2,
            "items_ai": [{"title": "AI post", "url": "https://example.com/a"}],
            "items_all": [{"title": "All post", "url": "https://example.com/b"}],
            "items_all_raw": [{"title": "Raw post", "url": "https://example.com/c"}],
        }
        slim, all_payload = build_latest_payloads(latest_payload)
        self.assertIn("items_ai", slim)
        self.assertNotIn("items_all", slim)
        self.assertNotIn("items_all_raw", slim)
        self.assertEqual(all_payload["items_all"][0]["title"], "All post")
        self.assertEqual(all_payload["items_all_raw"][0]["title"], "Raw post")

    def test_agentmail_digest_strips_body_addresses_and_secrets(self):
        payload = build_agentmail_digest_payload(
            [
                {
                    "message_id": "msg_private_1",
                    "timestamp": "2026-05-03T00:00:00Z",
                    "from": "Private Sender <newsletter@example.com>",
                    "to": ["reader@personal.example"],
                    "subject": "OpenAI update for reader@personal.example",
                    "preview": "New model notes. token=supersecret123 and contact reader@personal.example",
                    "text": "FULL PRIVATE BODY SHOULD NOT SHIP",
                    "html": "<p>FULL PRIVATE HTML SHOULD NOT SHIP</p>",
                    "extracted_text": "EXTRACTED BODY SHOULD NOT SHIP",
                    "labels": ["newsletter", "private-client"],
                    "attachments": [{"filename": "deck.pdf"}],
                }
            ],
            generated_at="2026-05-03T01:00:00Z",
            window_hours=24,
        )
        item = payload["items"][0]
        dumped = str(payload)
        self.assertEqual(payload["privacy"], "metadata_only_no_body")
        self.assertEqual(item["sender_domain"], "example.com")
        self.assertIn("[redacted-email]", item["subject"])
        self.assertIn("[redacted-secret]", item["preview"])
        self.assertTrue(item["has_attachments"])
        self.assertNotIn("newsletter@example.com", dumped)
        self.assertNotIn("reader@personal.example", dumped)
        self.assertNotIn("FULL PRIVATE BODY", dumped)
        self.assertNotIn("EXTRACTED BODY", dumped)
        self.assertNotIn("private-client", dumped)

    def test_agentmail_digest_can_filter_single_sender_domain(self):
        payload = build_agentmail_digest_payload(
            [
                {
                    "message_id": "msg_alpha",
                    "timestamp": "2026-05-03T00:00:00Z",
                    "from": "AlphaSignal <daily@mail.alphasignal.ai>",
                    "subject": "AI research digest",
                    "preview": "New papers and repos",
                },
                {
                    "message_id": "msg_other",
                    "timestamp": "2026-05-03T00:00:00Z",
                    "from": "Other Newsletter <news@example.com>",
                    "subject": "Should not be included",
                    "preview": "Noise",
                },
            ],
            generated_at="2026-05-03T01:00:00Z",
            window_hours=24,
            allowed_sender_domains=["alphasignal.ai"],
        )
        self.assertEqual(payload["allowed_sender_domains"], ["alphasignal.ai"])
        self.assertEqual(payload["total_messages"], 1)
        self.assertEqual(payload["items"][0]["sender_domain"], "mail.alphasignal.ai")
        self.assertIn("AI research digest", payload["items"][0]["subject"])

    def test_fetch_agentmail_digest_uses_list_messages_endpoint_only(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "messages": [
                        {
                            "message_id": "msg_2",
                            "timestamp": "2026-05-03T00:00:00Z",
                            "from": "AI Newsletter <news@example.com>",
                            "subject": "Claude ships a new feature",
                            "preview": "Short public-ish preview",
                        }
                    ]
                }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse()

        session = FakeSession()
        payload = fetch_agentmail_digest(
            session,
            api_key="test-key",
            inbox_id="inbox_123",
            generated_at="2026-05-03T01:00:00Z",
            after="2026-05-02T01:00:00Z",
            limit=10,
            base_url="https://api.agentmail.to",
        )
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.agentmail.to/v0/inboxes/inbox_123/messages")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["params"]["after"], "2026-05-02T01:00:00Z")
        self.assertNotIn("raw", url)
        self.assertEqual(payload["items"][0]["sender_domain"], "example.com")

    def test_agentmail_default_off_does_not_request_network(self):
        class NoNetworkSession:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("AgentMail should stay offline unless explicitly enabled")

        session = NoNetworkSession()
        with patch.dict("os.environ", {}, clear=True):
            payload, status = maybe_fetch_agentmail_digest(
                session,
                generated_at="2026-05-03T01:00:00Z",
                after="2026-05-02T01:00:00Z",
                window_hours=24,
            )
        self.assertIsNone(payload)
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["ok"])
        self.assertEqual(session.calls, 0)

    def test_agentmail_enabled_without_credentials_does_not_request_network(self):
        class NoNetworkSession:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("AgentMail should not fetch without full credentials")

        session = NoNetworkSession()
        with patch.dict("os.environ", {"EMAIL_DIGEST_ENABLED": "1"}, clear=True):
            payload, status = maybe_fetch_agentmail_digest(
                session,
                generated_at="2026-05-03T01:00:00Z",
                after="2026-05-02T01:00:00Z",
                window_hours=24,
            )
        self.assertIsNone(payload)
        self.assertTrue(status["enabled"])
        self.assertFalse(status["ok"])
        self.assertEqual(status["error"], "missing_agentmail_credentials")
        self.assertEqual(session.calls, 0)

    def test_x_api_default_off_does_not_request_network(self):
        class NoNetworkSession:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("X API should stay offline unless explicitly enabled")

        session = NoNetworkSession()
        with patch.dict("os.environ", {}, clear=True):
            items, status = maybe_fetch_x_api_updates(session, __import__("datetime").datetime.fromisoformat("2026-05-03T01:00:00+00:00"))
        self.assertEqual(items, [])
        self.assertFalse(status["enabled"])
        self.assertEqual(session.calls, 0)

    def test_x_api_enabled_outside_daily_window_does_not_request_network(self):
        class NoNetworkSession:
            def __init__(self):
                self.calls = 0

            def get(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("X API should wait for its daily run window")

        session = NoNetworkSession()
        env = {"X_API_ENABLED": "1", "X_BEARER_TOKEN": "test", "X_API_RUN_UTC_HOUR": "0"}
        with patch.dict("os.environ", env, clear=True):
            items, status = maybe_fetch_x_api_updates(session, __import__("datetime").datetime.fromisoformat("2026-05-03T01:00:00+00:00"))
        self.assertEqual(items, [])
        self.assertTrue(status["enabled"])
        self.assertTrue(status["skipped"])
        self.assertEqual(status["skip_reason"], "outside_x_api_daily_window")
        self.assertEqual(session.calls, 0)

    def test_x_api_force_run_maps_recent_search_posts(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": [
                        {
                            "id": "12345",
                            "author_id": "u1",
                            "text": "OpenAI ships a useful AI agent update",
                            "created_at": "2026-05-03T00:00:00Z",
                            "lang": "en",
                            "public_metrics": {"like_count": 10},
                        }
                    ],
                    "includes": {"users": [{"id": "u1", "username": "builder"}]},
                }

        class FakeSession:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse()

        session = FakeSession()
        env = {"X_API_ENABLED": "1", "X_BEARER_TOKEN": "test", "X_API_FORCE_RUN": "1", "X_API_MAX_RESULTS": "10"}
        with patch.dict("os.environ", env, clear=True):
            items, status = maybe_fetch_x_api_updates(session, __import__("datetime").datetime.fromisoformat("2026-05-03T01:00:00+00:00"))
        self.assertTrue(status["ok"])
        self.assertEqual(status["item_count"], 1)
        self.assertEqual(status["estimated_cost_usd"], 0.005)
        self.assertEqual(items[0].site_id, "xapi")
        self.assertEqual(items[0].source, "@builder")
        self.assertEqual(items[0].url, "https://x.com/builder/status/12345")
        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.x.com/2/tweets/search/recent")
        self.assertEqual(kwargs["params"]["max_results"], 10)


if __name__ == "__main__":
    unittest.main()
