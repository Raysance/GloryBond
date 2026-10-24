"""Pagination stays on the existing signed HTTP adapter."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


ADAPTER = import_hok_module("api_adapters.wzry")
ENCODER = import_hok_module("tools.endecoder")


class WzryPaginationRequestTests(unittest.TestCase):
    def test_page_cursor_is_sent_to_existing_post_endpoint(self):
        credentials = dict.fromkeys(("pubkey", "userid", "roleid", "encoderes", "gameopenid", "gameroleid",
                                     "openid", "tinkerid", "token", "x-log-uid"), "fixture")
        signature = dict.fromkeys(("crand", "encodeparam", "traceparent"), "fixture")
        response = SimpleNamespace(status_code=200, text=json.dumps({"data": {"list": [], "hasMore": False}}))
        with (patch.object(ADAPTER, "confs", {"wzry": credentials}),
              patch.object(ADAPTER, "refresh_login_credentials"),
              patch.object(ENCODER, "get_full_request_params", return_value=signature),
              patch.object(ADAPTER.requests, "post", return_value=response) as post):
            for reqtype, cursor in (("btlist", 0), ("btlist_url", 1792750000)):
                ADAPTER.wzry_get_official(reqtype, userid=1001, roleid=42, last_time=cursor)
                request = post.call_args
                self.assertEqual(request.args[0], "https://kohcamp.qq.com/game/morebattlelist")
                self.assertEqual(request.kwargs["json"], {
                    "lastTime": cursor, "recommendPrivacy": 0, "apiVersion": 5,
                    "friendRoleId": "42", "isMultiGame": 1, "friendUserId": "1001", "option": 0,
                })


if __name__ == "__main__":
    unittest.main()
