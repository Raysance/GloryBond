"""Pagination is passed unchanged to the SDK application boundary."""
import unittest
from unittest.mock import patch
from local_debugger import import_hok_module

ADAPTER = import_hok_module("api_adapters.wzry")

class WzryPaginationRequestTests(unittest.TestCase):
    def test_page_cursor_is_forwarded_without_local_protocol_generation(self):
        with (patch.object(ADAPTER, "data_root", "/private/data"),
              patch.object(ADAPTER, "refresh_login_credentials") as refresh,
              patch.object(ADAPTER, "query", return_value={"list": [], "hasMore": False}) as query):
            for reqtype, cursor in (("btlist", 0), ("btlist_url", "1700000000")):
                result = ADAPTER.wzry_get_official(reqtype, userid=1001, roleid=42, last_time=cursor)
                self.assertEqual(result, {"list": [], "hasMore": False})
                self.assertEqual(query.call_args.args[:4], (ADAPTER.session_path("/private/data"), reqtype, 1001, 42))
                self.assertEqual(query.call_args.kwargs["last_time"], cursor)
            self.assertEqual(refresh.call_count, 2)

if __name__ == "__main__":
    unittest.main()
