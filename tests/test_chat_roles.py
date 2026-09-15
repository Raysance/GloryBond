import unittest

from local_debugger import import_hok_module


ROLES = import_hok_module("chat_roles")


class ChatRoleTests(unittest.TestCase):
    def test_builtin_makise_role_is_available(self):
        role = ROLES.get_role("makise_kurisu")

        self.assertEqual(role.display_name, "牧濑红莉栖")
        self.assertIn("脑科学领域", role.profile)
        self.assertIn("【身份与经历】", role.profile)
        self.assertIn("【性格】", role.profile)
        self.assertIn("【思考与交流方式】", role.profile)
        self.assertIn("【语言风格】", role.profile)
        self.assertIn("【人际态度】", role.profile)
        self.assertIn("区分事实、推测与个人感受", role.profile)
        self.assertNotIn("安全要求", role.profile)

    def test_common_instructions_are_appended_after_role_profile(self):
        prompt = ROLES.build_role_prompt("makise_kurisu")

        self.assertLess(prompt.index("【角色信息：牧濑红莉栖】"), prompt.index("【角色扮演通用指令】"))
        self.assertIn("事实准确性、对话上下文与安全要求", prompt)

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
