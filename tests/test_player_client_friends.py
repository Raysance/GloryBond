"""Game-friend commands preserve exact identity and fresh, readable snapshots."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_debugger import import_hok_module
from hok_research import FriendList, PlayerPresence, PlayerRef, QueryTimeout

HANDLER = import_hok_module("event_handlers.player_client")
ADAPTER = import_hok_module("api_adapters.player_client")
BUSINESS = import_hok_module("business.player_client")
STATIC = import_hok_module("zstatic")
ZFUNC = import_hok_module("zfunc")
RULES = import_hok_module("event_rules")


def presence(name="游戏昵称", uid=7, world=8, online=1, **fields):
    raw = {"stFriendInfo": {"stUin": {"ullUid": uid, "dwLogicWorldId": world},
                           "szUserName": name.encode(), "bIsOnline": online},
           "bGameState": 2, "bGameSubState": 3, "bMaptype": 3, "dwMapId": 1,
           "dwHeroId": 106, "dwGameStartTime": 1792852800,
           "stTeamBriefInfo": {"bCurMemberNum": 3, "bMaxMemberNum": 5},
           "private": "PRIVATE_SENTINEL", **fields}
    return PlayerPresence(PlayerRef(uid, world), "game_friend", raw, True)


class FriendCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = {**STATIC.player_client_config, "players": {
            "alice": {"uid": 7, "logic_world_id": 8, "fake_description_id": 9}}}
        for field, value in {"player_client_config": self.settings, "qid": {"alice": "1"},
                             "namenick": {"alice": "甲"}, "extra_namenick": {},
                             "nameref": {"alice": ["甲", "ali"]}}.items():
            patcher = patch.object(STATIC, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def event(self, text, user="999"):
        return SimpleNamespace(get_plaintext=lambda: text, get_user_id=lambda: user)

    async def test_compact_spaced_and_fullwidth_commands_share_one_handler(self):
        for text, operation in (("#客户端好友", "friends"), ("＃客户端 好友列表", "friends"),
                                ("#客户端好友状态", "friend_states")):
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                 patch.object(ZFUNC, "player_client_text_report", return_value=["好友摘要"]) as report:
                event = self.event(text)
                self.assertTrue(await RULES.judge_player_client(event))
                self.assertEqual(await HANDLER.command_reply(event), ["好友摘要"])
                query.assert_called_once_with(operation)
                report.assert_called_once_with(operation, "当前登录角色", {}, page=1)

    async def test_friend_list_does_not_require_requester_binding_and_page_is_local(self):
        self.settings["players"] = {}
        with patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
             patch.object(ZFUNC, "player_client_text_report", return_value=["第二页"]) as report:
            await HANDLER.command_reply(self.event("#客户端 好友 2"))
        query.assert_called_once_with("friends")
        self.assertEqual(report.call_args.kwargs, {"page": 2})

    async def test_single_friend_uses_configured_uid_world_and_trusted_self(self):
        for text, user in (("#客户端好友状态 甲", "999"), ("＃客户端 好友状态 ALI", "999"),
                           ("#客户端 好友状态 我", "1")):
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                 patch.object(ZFUNC, "player_client_text_report", return_value=["状态"]):
                await HANDLER.command_reply(self.event(text, user))
                query.assert_called_once_with("friend_state", player=self.settings["players"]["alice"])

    async def test_invalid_pages_other_players_friend_lists_and_unbound_targets_do_not_query(self):
        with patch.object(ZFUNC, "player_client_query") as query:
            for text in ("#客户端 好友 0", "#客户端 好友 -1", "#客户端 好友 alice",
                         "#客户端 好友状态 alice extra", "#客户端 好友状态 陌生人",
                         "#客户端 好友状态 我", "#客户端 friend_state"):
                with self.subTest(text=text):
                    self.assertTrue(await HANDLER.command_reply(self.event(text)))
            query.assert_not_called()
        for text in ("客户端好友", "#客户端好友状态啊", "#客户端好友列表外", "##客户端好友"):
            with self.subTest(text=text):
                self.assertFalse(await RULES.judge_player_client(self.event(text)))

    async def test_transport_error_is_not_reported_as_empty_friends_or_offline(self):
        with patch.object(ZFUNC, "player_client_query", side_effect=QueryTimeout()) as query:
            result = await HANDLER.command_reply(self.event("#客户端 好友状态"))
        query.assert_called_once_with("friend_states")
        self.assertIn("失败", "".join(result))
        self.assertNotIn("离线", "".join(result))
        self.assertNotIn("暂无游戏好友", "".join(result))


class FriendAdapterTests(unittest.TestCase):
    def adapter(self):
        adapter = ADAPTER.PlayerClientAdapter.__new__(ADAPTER.PlayerClientAdapter)
        adapter.settings = {"timeout_seconds": 1}
        adapter.client, adapter.gate, adapter.on_error = Mock(), Mock(), Mock()
        adapter.client.friends.return_value = FriendList((presence().raw,), True, 1)
        return adapter

    def test_batch_states_read_passive_membership_and_gate_only_actual_refreshes(self):
        adapter = self.adapter()
        players = (presence(), presence("同UID另一服", world=99, online=0))
        adapter.client.friends.return_value = FriendList(tuple(p.raw for p in players), True, 2)
        adapter.client.refresh_friend_states.return_value = adapter.client.friends.return_value
        for operation in ("friends", "friend_states", "friend_states"):
            result = adapter.query(operation)
            self.assertTrue(result["complete"])
            self.assertEqual(result["total"], 2)
            self.assertEqual(len(result["players"]), 2)
            self.assertEqual(result["players"][0]["ranked_party_size"], 3)
        self.assertEqual(adapter.client.friends.call_count, 3)
        self.assertEqual(adapter.client.refresh_friend_states.call_count, 2)
        self.assertEqual([c.args[0] for c in adapter.gate.call_args_list], ["query"] * 2)
        adapter.client.server_time.assert_not_called()
        adapter.client.friend_states.assert_not_called()
        adapter.client.profile.assert_not_called()
        adapter.client.friend_state.assert_not_called()
        adapter.client.add_friend.assert_not_called()

    def test_single_friend_passes_full_reference_and_absence_is_explicit(self):
        adapter = self.adapter()
        ref = {"uid": 7, "logic_world_id": 99, "fake_description_id": 9}
        offline = presence(world=99, online=0)
        adapter.client.friends.return_value = FriendList((presence().raw, offline.raw), True, 2)
        result = adapter.query("friend_state", player=ref)
        adapter.client.friends.assert_called_once_with(timeout=1)
        adapter.client.refresh_friend_states.assert_not_called()
        self.assertTrue(result["found"])
        self.assertFalse(result["state"]["online"])
        adapter.client.friends.return_value = FriendList((presence().raw,), True, 1)
        self.assertEqual(adapter.query("friend_state", player=ref), {"found": False, "state": None})
        adapter.client.friend_state.assert_not_called()

    def test_online_single_friend_reads_the_same_refreshed_list_by_full_uid_world(self):
        adapter = self.adapter()
        base = FriendList((presence().raw,), True, 1)
        fresh = presence('刷新后的昵称')
        adapter.client.friends.return_value = base
        adapter.client.refresh_friend_states.return_value = FriendList((fresh.raw,), True, 1)
        result = adapter.query('friend_state', player={'uid': 7, 'logic_world_id': 8, 'fake_description_id': 9})
        self.assertEqual(result['state']['name'], '刷新后的昵称')
        adapter.client.refresh_friend_states.assert_called_once_with(base, timeout=1)
        self.assertEqual(adapter.gate.call_count, 1)
        adapter.client.server_time.assert_not_called()

    def test_account_friend_list_cannot_silently_ignore_a_supplied_other_player(self):
        adapter = self.adapter()
        for operation in ("friends", "friend_states"):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                adapter.query(operation, player={"uid": 7, "logic_world_id": 8, "fake_description_id": 0})
        adapter.gate.assert_not_called()
        adapter.client.friends.assert_not_called()

    def test_gate_and_timeout_propagate_without_retry_or_empty_snapshot(self):
        adapter = self.adapter()
        adapter.gate.side_effect = ADAPTER.PlayerClientRateLimited(50)
        with self.assertRaises(ADAPTER.PlayerClientRateLimited):
            adapter.query("friend_states")
        adapter.client.friends.assert_called_once()
        adapter.client.refresh_friend_states.assert_not_called()
        adapter.client.friends.reset_mock()
        adapter.gate.side_effect = None
        adapter.client.friends.side_effect = QueryTimeout()
        with self.assertRaises(QueryTimeout):
            adapter.query("friend_states")
        adapter.client.friends.assert_called_once()
        adapter.on_error.assert_called_once()

    def test_failed_or_blocked_state_refresh_never_returns_the_initial_friend_list_as_fresh(self):
        adapter = self.adapter()
        base = FriendList((presence().raw,), True, 1)
        adapter.client.friends.return_value = base
        adapter.gate.side_effect = ADAPTER.PlayerClientRateLimited(50)
        with self.assertRaises(ADAPTER.PlayerClientRateLimited):
            adapter.query('friend_states')
        adapter.client.refresh_friend_states.assert_not_called()
        adapter.gate.side_effect = None
        adapter.client.refresh_friend_states.side_effect = QueryTimeout()
        with self.assertRaises(QueryTimeout):
            adapter.query('friend_states')
        adapter.client.refresh_friend_states.assert_called_once_with(base, timeout=1)
        adapter.on_error.assert_called_once()

    def test_offline_roster_does_not_send_an_unnecessary_state_refresh(self):
        adapter = self.adapter()
        adapter.client.friends.return_value = FriendList((presence(online=0).raw,), True, 1)
        self.assertFalse(adapter.query('friend_states')['players'][0]['online'])
        adapter.client.refresh_friend_states.assert_not_called()
        self.assertEqual(adapter.gate.call_count, 0)


class FriendPresentationTests(unittest.TestCase):
    def render(self, operation, result, page=1):
        settings = {"display_item_limit": 5, "friend_page_size": 2,
                    "max_result_chars": 24000, "message_chars": 100}
        parts = BUSINESS.text_report(operation, "当前登录角色", result, settings, {"106": "小乔"}, page=page)
        self.assertTrue(all(len(part) <= 100 for part in parts))
        text = "".join(parts)
        for forbidden in ("PRIVATE_SENTINEL", "stFriendInfo", "logic_world_id", "game_state_code", "raw"):
            self.assertNotIn(forbidden, text)
        return text

    def test_online_mode_hero_party_and_actual_team_size_are_translated(self):
        text = self.render("friend_states", {"complete": True, "players": [presence().to_json_value()]})
        for expected in ("客户端好友状态", "游戏昵称", "在线", "对局中", "排位赛", "小乔", "三排", "队伍3/5人", "开局"):
            self.assertIn(expected, text)
        self.assertNotIn("五排", text)
        state = presence(bMaptype=9, dwMapId=5466).to_json_value()
        text = self.render("friend_state", {"found": True, "state": state})
        self.assertIn("共鸣之战", text)
        self.assertIn("队伍3/5人", text)
        self.assertNotIn("三排", text)

    def test_offline_hidden_and_unknown_status_never_show_stale_activity(self):
        for online, hidden, expected in ((False, False, "离线"), (False, True, "隐身"), (None, False, "状态未知")):
            state = {**presence().to_json_value(), "online": online, "hidden": hidden}
            text = self.render("friend_state", {"found": True, "state": state})
            self.assertIn(expected, text)
            for stale in ("对局中", "排位赛", "小乔", "三排", "队伍", "开局"):
                self.assertNotIn(stale, text)

    def test_capacity_does_not_become_party_size_and_unknown_states_stay_unknown(self):
        state = presence().to_json_value()
        state.update(game_state=None, game_substate=None, current_mode={"name": None},
                     hero_id=None, ranked_party_size=None, current_team_members=None)
        text = self.render("friend_state", {"found": True, "state": state})
        self.assertIn("状态未知", text)
        self.assertNotIn("五排", text)
        self.assertNotIn("队伍", text)

    def test_empty_partial_absent_and_offline_are_distinct(self):
        text = self.render("friends", {"complete": True, "players": []})
        self.assertIn("暂无游戏好友", text)
        text = self.render("friends", {"complete": False, "players": []})
        self.assertIn("列表未完整", text)
        self.assertNotIn("暂无游戏好友", text)
        text = self.render("friend_state", {"found": False, "state": None})
        self.assertIn("没有该玩家", text)
        self.assertNotIn("离线", text)

    def test_pages_keep_all_friends_accessible_and_list_view_stays_brief(self):
        result = {"complete": True, "players": [presence(name, uid=i, online=0).to_json_value()
                                                for i, name in enumerate(("A", "B", "C"), 1)]}
        first = self.render("friends", result)
        second = self.render("friends", result, page=2)
        self.assertIn("共3位好友", first)
        self.assertIn("1. A：离线", first)
        self.assertNotIn("3. C", first)
        self.assertIn("下一页：#客户端 好友 2", first)
        self.assertIn("3. C：离线", second)
        self.assertNotIn("1. A", second)
        self.assertIn("页码超出范围", self.render("friends", result, page=3))


if __name__ == "__main__":
    unittest.main()
