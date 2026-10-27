import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


class BiliVideoBusinessTests(unittest.TestCase):
    def test_legacy_string_subscription_is_normalized(self):
        normalized = ZFUNC._bili_video_normalize_subscriptions({"10001": "UP主"})
        self.assertEqual(
            normalized,
            {
                "10001": [
                    {
                        "up_mid": "",
                        "up_name": "UP主",
                        "query": "UP主",
                        "subscribed_at": "",
                    }
                ]
            },
        )

    def test_subscription_identity_prefers_mid(self):
        self.assertEqual(ZFUNC._bili_video_identity_key("123", "旧昵称"), "mid:123")
        self.assertEqual(ZFUNC._bili_video_seen_key("123", "旧昵称"), "hok:bili:seen:123")

    def test_matching_prefers_exact_mid_over_partial_name(self):
        items = [
            {"up_mid": "123", "up_name": "测试UP", "query": "测试"},
            {"up_mid": "456", "up_name": "测试UP二号", "query": "测试二号"},
        ]
        matches = ZFUNC._bili_video_find_matching_items(items, "123")
        self.assertEqual(matches, [(0, items[0])])

    def test_picture_url_and_cq_content_are_normalized(self):
        video = {"pic": "//i.example/image.jpg"}
        self.assertEqual(
            ZFUNC._bili_video_pic_url(video),
            "https://i.example/image.jpg",
        )
        self.assertEqual(
            ZFUNC._bili_video_pic_message_segment(video),
            "[CQ:image,file=https://i.example/image.jpg]",
        )


if __name__ == "__main__":
    unittest.main()
