import json
import unittest
from datetime import datetime, timezone

from web.request_analytics import (
    RECENT_REQUESTS_KEY,
    analytics_payload,
    enrich_request_event,
    geo_cache_key,
    sanitized_query,
    should_track_request,
)
from web.tools.import_request_analytics import parse_nginx_line


class FakeRedis:
    def __init__(self, values=None, lists=None):
        self.values = values or {}
        self.lists = lists or {}

    def get(self, key):
        return self.values.get(key)

    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]


class RequestAnalyticsTests(unittest.TestCase):
    def test_nginx_backfill_parser_uses_the_same_filtering_rules(self):
        cutoff = datetime(2026, 9, 21, tzinfo=timezone.utc)
        valid = (
            '203.0.113.8 - - [23/Sep/2026:07:45:19 +0800] '
            '"GET /person?key=secret&roleid=123 HTTP/1.1" 200 100 "-" "Mozilla/5.0" "-"\n'
        )
        intermediate = valid.replace("/person?key=secret&roleid=123", "/battle-data/456")
        redirect = valid.replace(' 200 100 ', ' 301 100 ')

        event, route_key = parse_nginx_line(valid, cutoff)

        self.assertEqual(event["path"], "/person")
        self.assertEqual(event["query"], {"roleid": ["123"]})
        self.assertEqual(route_key, "secret")
        self.assertIsNone(parse_nginx_line(intermediate, cutoff))
        self.assertIsNone(parse_nginx_line(redirect, cutoff))

        first, _ = parse_nginx_line(valid, cutoff, source_reference="access.log:1")
        second, _ = parse_nginx_line(valid, cutoff, source_reference="access.log:2")
        self.assertNotEqual(first["id"], second["id"])

    def test_only_human_facing_business_routes_are_tracked(self):
        browser = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"
        self.assertTrue(should_track_request("/battle", "GET", browser))
        self.assertTrue(should_track_request("/analyze-battle", "GET", browser))
        self.assertFalse(should_track_request("/battle-data/123", "GET", browser))
        self.assertFalse(should_track_request("/file_transfer/temp_files/a.json", "GET", browser))
        self.assertFalse(should_track_request("/admin/dashboard", "GET", browser))
        self.assertFalse(should_track_request("/battle", "GET", "Googlebot/2.1"))

    def test_sensitive_query_fields_are_never_stored(self):
        params = sanitized_query(
            "key=temporary-secret&AdminKey=admin-secret&gameSeq=123&targetRoleId=456"
        )
        self.assertNotIn("key", params)
        self.assertNotIn("AdminKey", params)
        self.assertEqual(params["gameSeq"], ["123"])
        self.assertEqual(params["targetRoleId"], ["456"])

    def test_route_payload_adds_context_without_storing_route_key(self):
        redis_client = FakeRedis(values={
            "hok:web:artifact:temporary-secret": json.dumps({
                "caller": {"PlayerName": "测试玩家"},
                "DateFrom": "09-01",
                "DateTo": "09-23",
                "filename": "private-file-name",
            }, ensure_ascii=False).encode(),
        })
        event = {"path": "/period", "route_label": "周期战绩", "content": "周期战绩"}

        enriched = enrich_request_event(redis_client, event, "temporary-secret")

        self.assertIn("发起者=测试玩家", enriched["content"])
        self.assertIn("开始=09-01", enriched["content"])
        self.assertNotIn("temporary-secret", json.dumps(enriched, ensure_ascii=False))
        self.assertNotIn("private-file-name", json.dumps(enriched, ensure_ascii=False))

    def test_payload_aggregates_geography_and_masks_ip(self):
        ip = "203.0.113.42"
        event = {
            "id": "event-1",
            "timestamp": 1_800_000_000,
            "method": "GET",
            "path": "/battle",
            "route_label": "对局详情",
            "content": "对局详情 · gameSeq=123",
            "query": {"gameSeq": ["123"]},
            "status": 200,
            "duration_ms": 12.3,
            "ip": ip,
            "user_agent": "Mozilla/5.0",
            "referer": "",
        }
        geo = {
            "status": "ok",
            "country": "中国",
            "region": "上海",
            "city": "上海",
            "latitude": 31.2,
            "longitude": 121.5,
            "label": "中国 · 上海 · 上海",
        }
        redis_client = FakeRedis(
            values={geo_cache_key(ip): json.dumps(geo, ensure_ascii=False).encode()},
            lists={RECENT_REQUESTS_KEY: [json.dumps(event, ensure_ascii=False).encode()]},
        )

        payload = analytics_payload(redis_client, "secret", limit=100)

        self.assertEqual(payload["summary"]["requests"], 1)
        self.assertEqual(payload["summary"]["unique_visitors"], 1)
        self.assertEqual(payload["distribution"][0]["location"], "中国 · 上海 · 上海")
        self.assertEqual(payload["events"][0]["masked_ip"], "203.0.*.*")
        self.assertNotIn("ip", payload["events"][0])
        self.assertNotIn("referer", payload["events"][0])
        self.assertNotIn("user_agent", payload["events"][0])


if __name__ == "__main__":
    unittest.main()
