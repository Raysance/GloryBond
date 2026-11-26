import unittest

from tools.debugger import import_project_module


ZAPI = import_project_module("glorybond.integrations.api")
ZFUNC = import_project_module("glorybond.features.facade")


class ZapiBoundaryTests(unittest.TestCase):
    def test_low_priority_gate_stays_in_business_layer(self):
        original_api = ZAPI.wzry_get_official
        original_wait = ZFUNC._wait_official_low_priority_turn
        calls = []

        ZAPI.wzry_get_official = lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ) or {"ok": True}
        ZFUNC._wait_official_low_priority_turn = lambda: calls.append("waited")
        try:
            result = ZFUNC.wzry_get_official(
                reqtype="btlist",
                userid="1",
                roleid="2",
                priority="low",
            )
        finally:
            ZAPI.wzry_get_official = original_api
            ZFUNC._wait_official_low_priority_turn = original_wait

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0], "waited")
        self.assertEqual(
            calls[1],
            ((), {"reqtype": "btlist", "userid": "1", "roleid": "2"}),
        )


if __name__ == "__main__":
    unittest.main()
