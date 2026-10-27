import hashlib
import json
import unittest

from local_debugger import import_hok_module


WEB_ARTIFACTS = import_hok_module("business.web_artifacts")
ZFUNC = import_hok_module("zfunc")


class FakeRedis:
    def __init__(self):
        self.calls = []

    def set(self, key, value, **kwargs):
        self.calls.append((key, value, kwargs))
        return True


class WebArtifactTests(unittest.TestCase):
    def test_seeded_hash_is_stable_and_short(self):
        expected = hashlib.sha256(b"123").hexdigest()[:16]
        self.assertEqual(WEB_ARTIFACTS.make_hash(123), expected)

    def test_route_mapping_and_unknown_type(self):
        self.assertEqual(
            WEB_ARTIFACTS.route_url("bili_video", "abc", "example.com"),
            "https://hok.example.com/bili-video?key=abc",
        )
        self.assertEqual(
            WEB_ARTIFACTS.route_url("unknown", "abc", "example.com"),
            "",
        )

    def test_history_payload_keeps_extra_fields(self):
        self.assertEqual(
            WEB_ARTIFACTS.history_route_payload(
                "abc",
                "alice",
                "2026-09-23 12:00:00",
                {"DateFrom": "09-01"},
            ),
            {
                "filename": "abc",
                "caller": "alice",
                "time": "2026-09-23 12:00:00",
                "DateFrom": "09-01",
            },
        )

    def test_facade_keeps_redis_storage_in_zfunc(self):
        original_redis = ZFUNC.dmc.redis_deamon
        original_hash = ZFUNC.WebArtifacts.__dict__["make_hash"]
        original_web_service = ZFUNC.confs.get("WebService")
        fake_redis = FakeRedis()
        ZFUNC.dmc.redis_deamon = fake_redis
        ZFUNC.confs["WebService"] = {"server_domain": "example.com"}
        ZFUNC.WebArtifacts.make_hash = staticmethod(lambda seed=None: "fixed")
        try:
            link = ZFUNC.WebArtifacts.history_route_link(
                "history-id",
                "query_select",
                "alice",
                "now",
            )
        finally:
            ZFUNC.dmc.redis_deamon = original_redis
            ZFUNC.WebArtifacts.make_hash = original_hash
            if original_web_service is None:
                ZFUNC.confs.pop("WebService", None)
            else:
                ZFUNC.confs["WebService"] = original_web_service

        self.assertEqual(link, "https://hok.example.com/query?key=fixed")
        self.assertEqual(len(fake_redis.calls), 1)
        key, value, options = fake_redis.calls[0]
        self.assertEqual(key, "hok:web:artifact:fixed")
        self.assertEqual(
            json.loads(value),
            {
                "filename": "history-id",
                "caller": "alice",
                "time": "now",
            },
        )
        self.assertEqual(options, {"ex": ZFUNC.REDIS_TEXT_EXPIRE_SECONDS})


if __name__ == "__main__":
    unittest.main()
