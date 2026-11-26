import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageFont

from glorybond.rendering import gen_coplayer_analyses as template


FONT = Path(__file__).resolve().parents[1] / "resources/fonts/noto-sans-sc/NotoSansSC-VF.ttf"


def font_loader(size, bold=False):
    font = ImageFont.truetype(str(FONT), size)
    font.set_variation_by_axes([700 if bold else 400])
    return font


class WatchStrengthTemplateTests(unittest.TestCase):
    def test_partial_data_keeps_template_columns_without_inferred_values_or_io(self):
        players = [template.PlayerInfo(name="示例玩家", side="my", auth=None,
                                       hero_avatar_url="https://example.invalid/hero",
                                       avatar_path="https://example.invalid/avatar")]
        texts = []
        cards = []
        original_text = template._safe_text
        original_box = template._rounded_rectangle

        def record_text(draw, xy, value, *args, **kwargs):
            texts.append(value)
            return original_text(draw, xy, value, *args, **kwargs)

        def record_box(draw, xy, radius, **kwargs):
            cards.append((radius, kwargs.get("fill")))
            return original_box(draw, xy, radius, **kwargs)

        with patch.object(template, "_calc_display_score", side_effect=AssertionError("inferred score")), \
             patch.object(template, "_batch_load_hero_icons", side_effect=AssertionError("asset fetch")), \
             patch.object(template, "_batch_load_avatars", side_effect=AssertionError("asset fetch")), \
             patch.object(template.urllib.request, "urlopen", side_effect=AssertionError("network")), \
             patch.object(Image, "open", side_effect=AssertionError("image file read")), \
             patch.object(Image.Image, "save", side_effect=AssertionError("image file write")), \
             patch.object(template, "_safe_text", record_text), \
             patch.object(template, "_rounded_rectangle", record_box):
            image = template.render_player_strength_image(
                players, title="对局阵容", partial_data=True, font_loader=font_loader,
                team_labels=("阵营 1", "阵营 2"),
            )
        self.assertEqual((image.width, image.mode), (1600, "RGB"))
        for label in ("阵营 1", "阵营 2", "英雄\n战力", "英雄\n场次", "总MVP率"):
            self.assertIn(label, texts)
        for fabricated in ("0", "0.0%", "-", "历史实力", "H"):
            self.assertNotIn(fabricated, texts)
        self.assertIn((18, (240, 243, 248)), cards)

    def test_observed_values_and_assets_render_without_filling_unknown_metrics(self):
        players = [template.PlayerInfo(name="青山", side="my", auth=None, hero_name="示例英雄",
                                       hero_avatar_url="hero", avatar_path="avatar",
                                       hero_power=3210, wins=7, losses=4, win_rate=7 / 11),
                   template.PlayerInfo(name="南风", side="op", auth=None, hero_power=0,
                                       wins=0, losses=0)]
        before = copy.deepcopy(players)
        sources = {"hero": Image.new("RGBA", (30, 50), "blue"),
                   "avatar": Image.new("RGB", (30, 30), "orange")}
        pixels = {key: value.tobytes() for key, value in sources.items()}
        texts = []
        original = template._safe_text

        def record(draw, xy, value, *args, **kwargs):
            texts.append(value)
            return original(draw, xy, value, *args, **kwargs)

        with patch.object(template, "_calc_display_score", side_effect=AssertionError("inferred score")), \
             patch.object(template, "_safe_text", record):
            image = template.render_player_strength_image(
                players, partial_data=True, images=sources, font_loader=font_loader,
            )
        without_assets = template.render_player_strength_image(players, partial_data=True, font_loader=font_loader)
        self.assertEqual(players, before)
        self.assertEqual(pixels, {key: value.tobytes() for key, value in sources.items()})
        self.assertNotEqual(image.tobytes(), without_assets.tobytes())
        self.assertIn("3210", texts)
        self.assertIn("11", texts)
        self.assertIn("0", texts)  # Observed zero remains distinct from missing data.
        self.assertIn("示例英雄", texts)
        self.assertNotIn("0.0%", texts)
        self.assertNotIn("历史实力", texts)

    def test_legacy_save_api_still_works_and_retains_default_template_layout(self):
        players = [template.PlayerInfo(name="示例", side="my", auth=True, wins=2, losses=1,
                                       hero_power=1500, mvp_cnt=1, total_cnt=3, single_level=80)]
        partial = template.render_player_strength_image(players, partial_data=True, images={}, font_loader=font_loader)
        legacy = template.render_player_strength_image(players, images={}, font_loader=font_loader)
        self.assertEqual(partial.size, legacy.size)
        process = template.CoPlayerProcess()
        process.extend(players)
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / "strength.png")
            self.assertEqual(process.gen(path, images={}, font_loader=font_loader), (path, True))
            with Image.open(path) as saved:
                self.assertEqual(saved.size, legacy.size)

    def test_partial_colors_use_supplied_scores_with_original_red_green_palette(self):
        players = [template.PlayerInfo(name='高', side='my', score=90),
                   template.PlayerInfo(name='低', side='op', score=10),
                   template.PlayerInfo(name='未知', side='op')]
        colors = []
        original = template._rounded_rectangle
        def record(draw, xy, radius, **kwargs):
            if radius == 18:
                colors.append(kwargs.get('fill'))
            return original(draw, xy, radius, **kwargs)
        with patch.object(template, '_rounded_rectangle', record), \
             patch.object(template, '_calc_display_score', side_effect=AssertionError('invented metric')):
            template.render_player_strength_image(players, partial_data=True, font_loader=font_loader)
        self.assertEqual(colors[0], template._blend_with_white(template.ACCENT_GREEN, .24))
        self.assertEqual(colors[1], template._blend_with_white(template.ACCENT_RED, .24))
        self.assertEqual(colors[2], (240, 243, 248))

    def test_original_hero_artwork_and_all_avatars_are_loaded_before_rendering(self):
        from glorybond.storage import files
        import threading
        barrier = threading.Barrier(10)
        with tempfile.TemporaryDirectory() as root:
            icons = Path(root) / 'resources/wzry_images/custom_wzry_E1'
            icons.mkdir(parents=True)
            filename = '00dcf4e2c59503f0bca334e867d05299.jpg'
            Image.new('RGB', (80, 90), 'green').save(icons / filename)
            players = [{'hero_id': '107', 'hero_icon': 'https://cdn.example.com/custom_wzry_E1/' + filename,
                        'role_icon': f'https://cdn.example.com/avatar-{index}'} for index in range(10)]
            original_loader = files.load_battle_report_image
            def avatar(url, **kwargs):
                if 'custom_wzry_E1' in url:
                    return original_loader(url, **kwargs)
                self.assertIn('avatar-', url)
                barrier.wait(timeout=2)
                return Image.new('RGB', (40, 40), 'orange')
            with patch.object(files, 'project_root', root), patch.object(files, 'load_battle_report_image', side_effect=avatar) as load:
                images = files.load_watch_lineup_images({'teams': [{'players': players}]})
            self.assertEqual(len(images), 11)
            self.assertEqual(load.call_count, 11)
            self.assertEqual(images[players[0]['hero_icon']].size, (80, 90))


if __name__ == "__main__":
    unittest.main()
