import unittest

from local_debugger import import_hok_module


ROLES = import_hok_module("chat_roles")


class ChatRoleTests(unittest.TestCase):
    def test_builtin_makise_role_is_available(self):
        role = ROLES.get_role("makise_kurisu")

        self.assertEqual(role.display_name, "牧濑红莉栖")
        self.assertIn("天才脑科学研究者", ROLES.build_role_prompt(role.key))

    def test_unknown_or_disabled_role_has_no_prompt(self):
        self.assertEqual(ROLES.build_role_prompt(""), "")
        self.assertEqual(ROLES.build_role_prompt("not-installed"), "")

    def test_external_role_can_be_registered(self):
        custom = ROLES.ChatRole("portable_test", "测试角色", "保持简洁。")
        ROLES.register_role(custom, replace=True)

        self.assertIs(ROLES.get_role("portable_test"), custom)
        self.assertIn("保持简洁。", ROLES.build_role_prompt("portable_test"))

    def test_role_registration_rejects_accidental_overwrite(self):
        duplicate = ROLES.ChatRole("makise_kurisu", "替代角色", "不应覆盖。")

        with self.assertRaisesRegex(ValueError, "already registered"):
            ROLES.register_role(duplicate)

        self.assertEqual(ROLES.get_role("makise_kurisu").display_name, "牧濑红莉栖")

if __name__ == "__main__":
    unittest.main()
