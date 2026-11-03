"""Default emoji resources survive a fresh checkout and preserve template scope."""

from contextlib import chdir
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from local_debugger import import_hok_module


GEN = import_hok_module("tools.gen_emoji_image")
API = import_hok_module("zapi")
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "resources/wzry_images/emoji_template"
DEFAULT_NAMES = ("001_asuka_明日香.webp", "002_kurisu_牧濑红莉栖.jpg", "003_kaguya_辉夜.webp")


class EmojiTemplateTests(unittest.TestCase):
    def test_bundled_defaults_decode_and_support_number_and_name_selection(self):
        with patch.object(GEN, "_emoji_template_local_dir", return_value=str(TEMPLATES)), \
             patch.object(GEN, "_emoji_template_extra_dirs", return_value=[]):
            self.assertTrue(set(DEFAULT_NAMES) <= {
                Path(p).name for p in GEN._emoji_template_candidates(include_extra_dirs=False)})
            for name, query in zip(DEFAULT_NAMES, ("明日香", "牧濑红莉栖", "辉夜")):
                with self.subTest(name=name):
                    path = TEMPLATES / name
                    with Image.open(path) as image:
                        image.load()
                        self.assertGreater(image.width, 0)
                        self.assertGreater(image.height, 0)
                    self.assertEqual(Path(GEN._emoji_pick_template_by_prefix(name[:3])), path)
                    self.assertEqual(Path(GEN._emoji_pick_template_by_name(query)), path)

    def test_legacy_resource_path_resolves_outside_the_project_working_directory(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory), \
             patch.object(GEN, "project_root", str(ROOT)), \
             patch.object(GEN.dmc, "EmojiTemplateLocalDir", "/resources/wzry_images/emoji_template"):
            self.assertEqual(Path(GEN._emoji_template_local_dir()), TEMPLATES)
            self.assertIn(Path(GEN._emoji_pick_template_path(include_extra_dirs=False)).name, DEFAULT_NAMES)

    def test_empty_primary_does_not_randomly_select_extra_resources_or_call_image_api(self):
        with tempfile.TemporaryDirectory() as directory:
            primary, extra = Path(directory) / "primary", Path(directory) / "extra"
            primary.mkdir(); extra.mkdir()
            (extra / "extra_fixture.png").write_bytes(b"fixture")
            with patch.object(GEN, "_emoji_template_local_dir", return_value=str(primary)), \
                 patch.object(GEN, "_emoji_template_extra_dirs", return_value=[str(extra)]), \
                 patch.object(API, "apimart_images_generate") as generate, \
                 patch.object(GEN, "_emoji_pick_one_refined_message") as context:
                with self.assertRaises(GEN.EmojiTemplatesUnavailable):
                    GEN.generate_user_emoji_image(user_qid="101", group_id="200")
                generate.assert_not_called()
                context.assert_not_called()
                self.assertEqual(Path(GEN._emoji_pick_template_by_prefix("extra_fixture")),
                                 extra / "extra_fixture.png")


if __name__ == "__main__":
    unittest.main()
