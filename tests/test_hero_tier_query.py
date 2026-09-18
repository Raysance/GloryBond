import os
import tempfile
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")
ZFILE = import_hok_module("zfile")
try:
    from PIL import Image

    GEN_HERO_TIER = import_hok_module("tools.gen_hero_tier")
except ImportError:
    Image = None
    GEN_HERO_TIER = None


def tier_item(index, role, tier):
    return {
        "heroId": 100 + index,
        "heroName": f"英雄{index}",
        "avatarUrl": f"https://example.com/{index}.png",
        "date": "2026-09-18",
        "role": role,
        "trueHeroPowerInRole": 18000 - index * 100,
        "finalNormalizedTierScore": max(0, 80 - index * 4),
        "tierInRole": tier,
        "rankInRole": index,
        "lowPick": index % 3 == 0,
        "highBan": index % 5 == 0,
    }


@unittest.skipUnless(GEN_HERO_TIER is not None, "Pillow is not installed in this test environment")
class HeroTierQueryTests(unittest.TestCase):
    def setUp(self):
        roles = ("对抗路", "打野", "中路", "发育路", "游走")
        tiers = ("T0", "T0.5", "T1", "T2", "T3", "T4")
        self.payload = {
            "queryDate": "2026-09-18",
            "tiers": [tier_item(index, roles[index % 5], tiers[index % 6]) for index in range(1, 21)],
        }

    def test_generates_web_style_tier_grouped_long_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "tier.png")
            GEN_HERO_TIER.generate_hero_tier_image(self.payload, output_path)

            with Image.open(output_path) as image:
                self.assertEqual(image.width, 1800)
                self.assertGreater(image.height, 500)

    def test_process_uses_api_and_project_output_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "tier.png")
            missing_items = self.payload["tiers"][1:]
            with patch("hok.zapi.tianyuanzhiyi_tier_api", return_value=self.payload), patch(
                "hok.zfile.hero_tier_image_path", return_value=output_path
            ), patch(
                "hok.zapi.tianyuanzhiyi_hero_avatars_api", return_value={}
            ) as avatar_api, patch(
                "hok.zfile.load_hero_tier_avatar_cache",
                return_value=({"101": b"cached-avatar"}, missing_items),
            ), patch("hok.zfile.save_hero_tier_avatar_cache") as save_cache:
                result = ZFUNC.hero_tier_query_process()

            self.assertEqual(result, output_path)
            self.assertTrue(os.path.exists(output_path))
            avatar_api.assert_called_once_with(missing_items)
            save_cache.assert_called_once_with(missing_items, {})

    def test_each_query_regenerates_image_while_reusing_avatar_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "tier.png")
            with patch("hok.zapi.tianyuanzhiyi_tier_api", return_value=self.payload), patch(
                "hok.zfile.hero_tier_image_path", return_value=output_path
            ), patch(
                "hok.zfile.load_hero_tier_avatar_cache", return_value=({}, [])
            ), patch(
                "hok.zapi.tianyuanzhiyi_hero_avatars_api"
            ) as avatar_api, patch(
                "hok.tools.gen_hero_tier.generate_hero_tier_image"
            ) as generate_image:
                ZFUNC.hero_tier_query_process()
                ZFUNC.hero_tier_query_process()

            self.assertEqual(generate_image.call_count, 2)
            avatar_api.assert_not_called()

    def test_avatar_cache_key_changes_with_source_url(self):
        first = tier_item(1, "中路", "T0")
        second = dict(first, avatarUrl="https://example.com/new-avatar.png")
        first_path = ZFILE.hero_tier_avatar_cache_path(first)

        self.assertNotEqual(
            first_path,
            ZFILE.hero_tier_avatar_cache_path(second),
        )
        self.assertIn(os.path.join("resources", "wzry_images", "hero_avatars"), first_path)
        self.assertNotIn("file_transfer", first_path)

    def test_web_boundary_grouping_matches_page_thresholds(self):
        heroes = [
            tier_item(1, "中路", "T0.5"),
            tier_item(2, "打野", "T0.5"),
        ]
        heroes[0]["finalNormalizedTierScore"] = 69.5
        heroes[1]["finalNormalizedTierScore"] = 60.5

        groups = GEN_HERO_TIER._group_by_web_tier(heroes)

        self.assertEqual(groups["T0.5"]["upper"], [heroes[0]])
        self.assertEqual(groups["T0.5"]["lower"], [heroes[1]])

    def test_process_rejects_empty_api_response(self):
        with patch("hok.zapi.tianyuanzhiyi_tier_api", return_value={}):
            with self.assertRaisesRegex(Exception, "empty response"):
                ZFUNC.hero_tier_query_process()


if __name__ == "__main__":
    unittest.main()
