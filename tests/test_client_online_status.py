"""Official friend states drive #在线 without Camp requests or Steam changes."""
import unittest
from unittest.mock import patch

from hok_research import PlayerPresence, PlayerRef
from local_debugger import import_hok_module

ONLINE = import_hok_module("business.online_status")
ZFUNC = import_hok_module("zfunc")
ZAPI = import_hok_module("zapi")
ZTIME = import_hok_module("ztime")


def state(uid, name, *, world=100, game=2, sub=3, map_type=3, map_id=1,
          members=3, capacity=5, desk=10, relay=20, sequence=30, elapsed=480, online=1, hidden=False):
    raw = {"stFriendInfo": {"stUin": {"ullUid": uid, "dwLogicWorldId": world},
                           "szUserName": name.encode(), "bIsOnline": online},
           "bGameState": game, "bGameSubState": sub, "bMaptype": map_type, "dwMapId": map_id,
           "dwHeroId": 106, "dwGameStartTime": 1000, "dwOtherStateBits": 4 if hidden else 0,
           "stTeamBriefInfo": {"bCurMemberNum": members, "bMaxMemberNum": capacity},
           "bVideoState": 1,
           "stGameInfo": {"selector": 1, "type": "CSProtocol.COMDT_GAMEINFO_DETAIL", "value": {
               "stDesk": {"dwDeskID": desk, "dwRelayEntity": relay, "dwDeskCrtSeq": sequence}}}}
    return PlayerPresence(PlayerRef(uid, world), "game_friend", raw, True,
                          None if elapsed is None else 1000 + elapsed).to_json_value()


class ClientOnlineTests(unittest.TestCase):
    def setUp(self):
        self.bindings = {key: {"uid": i, "logic_world_id": 100, "nickname": key}
                         for i, key in enumerate(("a", "b", "c", "d", "e"), 1)}
        for obj, field, value in ((ONLINE, "userlist", {key: i for i, key in enumerate(self.bindings)}),
                                  (ONLINE, "player_client_config", {"players": self.bindings}),
                                  (ONLINE, "steam_userlist", {})):
            p = patch.object(obj, field, value)
            p.start(); self.addCleanup(p.stop)
        query = patch.object(ZFUNC, "player_client_query")
        camp = patch.object(ZFUNC, "wzry_get_official", side_effect=AssertionError("Camp must not be queried"))
        self.query, self.camp = query.start(), camp.start()
        self.addCleanup(query.stop)
        self.addCleanup(camp.stop)
        snapshot = patch.object(ZFUNC, 'player_client_online_snapshot', side_effect=lambda: self.query('friend_states'))
        snapshot.start(); self.addCleanup(snapshot.stop)

    def report(self, players):
        self.query.return_value = {"complete": True, "players": players}
        return ZFUNC.online_process()

    def test_approved_layout_moves_common_ranked_party_to_header_and_keeps_steam_verbatim(self):
        players = [state(1, "LYG.未央"), state(2, "示例玩家70"),
                   state(3, "冰阔落加白糖", map_type=9, map_id=5466, members=2, elapsed=300),
                   state(4, "LYG.KK", game=3, sub=1), state(5, "染尘烟夕", game=0, sub=0)]
        players[0]["hero_name"] = "东皇太一"
        players[1]["hero_name"] = "孙尚香"
        players[2]["hero_name"] = "蒙犽"
        players[2]["battle_id"]["desk_id"] = 11
        with patch.object(ONLINE, "steam_userlist", {"steam": "steam-1"}), \
             patch.dict(ONLINE.confs, {"Steam": {"api_key": "test"}}), \
             patch.object(ZAPI, "steam_api_user_status", return_value={
                 "personaname": "Steam昵称", "personastate": 1, "gameextrainfo": "Counter-Strike 2"}) as steam:
            message, errors = self.report(players)
        self.assertEqual(message, "\n".join((
            "在线 5 人", "─────────────", "🎮 排位赛 三排 3/5  8min",
            "   • LYG.未央  东皇太一", "   • 示例玩家70  孙尚香", "",
            "🎮 共鸣之战  5min", "   • 冰阔落加白糖  蒙犽  2/5", "",
            "─────────────", "👥 LYG.KK  排位赛 3/5", "💤 染尘烟夕", "",
            "Steam 在线 1 人", "─────────────", "🎮 Steam昵称  Counter-Strike 2", "", "只跟踪王者好友")))
        self.assertEqual(errors, "")
        self.query.assert_called_once_with("friend_states")
        steam.assert_called_once_with("test", "steam-1")
        self.camp.assert_not_called()

    def test_refreshed_team_gaming_state_from_resonance_sample_uses_game_layout_without_video_data(self):
        player = state(1, '合成玩家', game=3, sub=3, map_type=9, map_id=5466, members=1, elapsed=572)
        player.update(hero_id=108, hero_name='墨子', battle_id=None, ranked_party_size=None)
        message, errors = self.report([player])
        self.assertEqual(errors, '')
        self.assertEqual(message, '在线 1 人\n─────────────\n🎮 共鸣之战  9min\n   • 合成玩家  墨子  1/5\n\n只跟踪王者好友')
        self.query.assert_called_once_with('friend_states')

    def test_only_exact_configured_main_friends_are_counted_and_hidden_or_offline_are_skipped(self):
        self.bindings["extra"] = {"uid": 6, "logic_world_id": 100}
        players = [state(1, "A"), state(1, "A重复"), state(2, "同UID不同服", world=101),
                   state(3, "离线", online=0), state(4, "隐身", hidden=True),
                   state(6, "额外玩家"), state(99, "陌生人")]
        players.append({**state(5, "未知在线"), "online": None})
        message, errors = self.report(players)
        self.assertIn("在线 1 人", message)
        self.assertIn("• A", message)
        for forbidden in ("A重复", "同UID不同服", "离线", "隐身", "额外玩家", "陌生人", "未知在线", "未加好友"):
            self.assertNotIn(forbidden, message)
        self.assertEqual(errors, "")
        self.query.assert_called_once_with("friend_states")

    def test_distinct_battle_identities_stay_separate_from_snapshot_groups(self):
        players = [state(1, "A"), state(2, "B", sequence=31), state(3, "C", relay=21),
                   state(4, "D", desk=11), state(5, "E")]
        players[0]["battle_id"] = None
        players[4]["battle_id"] = None
        message, _ = self.report(players)
        self.assertEqual(message.count("🎮 排位赛"), 4)
        self.assertIn("在线 5 人", message)
        self.assertIn("• A  小乔\n   • E  小乔", message)

    def test_missing_battle_ids_group_resonance_players_with_identical_precise_snapshots(self):
        players = [state(index, name, game=3, sub=3, map_type=9, map_id=5466, elapsed=370)
                   for index, name in enumerate(("A", "B", "C"), 1)]
        for player, hero in zip(players, ("刘禅", "孙权", "雅典娜")):
            player.update(battle_id=None, hero_name=hero)
        players.append(state(4, "D"))
        message, errors = self.report(players)
        self.assertEqual(errors, "")
        self.assertEqual(message.count("🎮"), 2)
        self.assertIn("🎮 共鸣之战  6min\n   • A  刘禅  3/5\n"
                      "   • B  孙权  3/5\n   • C  雅典娜  3/5", message)
        self.assertIn("在线 4 人", message)
        self.query.assert_called_once_with("friend_states")

    def test_missing_battle_ids_require_identical_mode_seconds_members_and_capacity(self):
        variants = (
            ("current_mode", {"map_type": 8, "map_id": 5466, "name": "共鸣之战"}),
            ("current_mode", {"map_type": 9, "map_id": 5467, "name": "共鸣之战"}),
            ("game_elapsed_seconds", 371),
            ("current_team_members", 2),
            ("team_capacity", 6),
        )
        for field, value in variants:
            with self.subTest(field=field, value=value):
                players = [state(index, name, game=3, sub=3, map_type=9, map_id=5466, elapsed=370)
                           for index, name in enumerate(("A", "B"), 1)]
                for player in players:
                    player["battle_id"] = None
                players[1][field] = value
                message, errors = self.report(players)
                self.assertEqual(errors, "")
                self.assertEqual(message.count("🎮"), 2)

    def test_missing_battle_ids_do_not_group_when_a_snapshot_field_is_unknown(self):
        variants = (
            ("current_mode", None),
            ("current_mode", {"map_type": 9, "map_id": None, "name": "共鸣之战"}),
            ("current_mode", {"map_type": None, "map_id": 5466, "name": "共鸣之战"}),
            ("game_elapsed_seconds", None),
            ("current_team_members", None),
            ("team_capacity", None),
        )
        for field, value in variants:
            with self.subTest(field=field, value=value):
                players = [state(index, name, game=3, sub=3, map_type=9, map_id=5466, elapsed=370)
                           for index, name in enumerate(("A", "B"), 1)]
                for player in players:
                    player.update(battle_id=None)
                    player[field] = value
                message, errors = self.report(players)
                self.assertEqual(errors, "")
                self.assertEqual(message.count("🎮"), 2)

    def test_missing_battle_ids_can_group_at_zero_elapsed_seconds(self):
        players = [state(1, "A", elapsed=0), state(2, "B", elapsed=0)]
        for player in players:
            player["battle_id"] = None
        message, errors = self.report(players)
        self.assertEqual(errors, "")
        self.assertEqual(message.count("🎮"), 1)
        self.assertIn("0min", message)

    def test_shared_battle_with_different_party_sizes_keeps_party_on_each_player(self):
        message, _ = self.report([state(1, "A"), state(2, "B", members=2)])
        self.assertEqual(message.count("🎮 排位赛"), 1)
        self.assertIn("🎮 排位赛  8min", message)
        self.assertIn("• A  小乔  三排  3/5", message)
        self.assertIn("• B  小乔  双排  2/5", message)

    def test_grouping_and_match_queue_display_known_map_without_stale_idle_fields(self):
        message, _ = self.report([state(1, "组队共鸣", game=3, sub=1, map_type=9, map_id=5466),
                                  state(2, "匹配排位", game=3, sub=4),
                                  state(3, "地图未返回", game=3, sub=1, map_id=0),
                                  state(4, "空闲", game=0, sub=0)])
        self.assertIn("👥 组队共鸣  共鸣之战 3/5", message)
        self.assertIn("👥 匹配排位  排位赛 3/5", message)
        self.assertIn("👥 地图未返回  3/5", message)
        self.assertIn("💤 空闲\n\n只跟踪王者好友", message)
        self.assertNotIn("组队中", message)
        self.assertNotIn("未知", message)
        self.assertNotIn("🎮", message)

    def test_unknown_values_are_omitted_and_zero_server_duration_is_valid(self):
        one, two = state(1, "A", elapsed=0), state(2, "B", elapsed=None)
        two.update(current_mode=None, hero_name=None, ranked_party_size=None,
                   current_team_members=None, team_capacity=5, battle_id=None)
        message, _ = self.report([one, two])
        self.assertIn("0min", message)
        self.assertIn("🎮\n   • B", message)
        for forbidden in ("None", "未知", "0/0", "五排", "未取得", "客户端"):
            self.assertNotIn(forbidden, message)
        self.assertEqual(ZTIME.elapsed_minutes_text(480), "8min")
        self.assertEqual(ZTIME.elapsed_minutes_text(None), "")

    def test_client_failure_preserves_steam_and_does_not_leak_transport_material(self):
        self.query.side_effect = TimeoutError("PRIVATE_SENTINEL")
        with patch.object(ONLINE, "steam_userlist", {"steam": "steam-1"}), \
             patch.dict(ONLINE.confs, {"Steam": {"api_key": "test"}}), \
             patch.object(ZAPI, "steam_api_user_status", return_value={"personaname": "Steam昵称", "personastate": 1}):
            message, errors = ZFUNC.online_process()
        self.assertEqual(message, "Steam 在线 1 人\n─────────────\n💤 Steam昵称  在线\n\n只跟踪王者好友")
        self.assertIn("online.player_client", errors)
        self.assertNotIn("PRIVATE_SENTINEL", message + errors)
        self.camp.assert_not_called()
        self.query.assert_called_once()

    def test_failure_is_not_no_one_online_and_a_successful_empty_snapshot_keeps_old_copy(self):
        self.query.side_effect = TimeoutError()
        message, errors = ZFUNC.online_process()
        self.assertEqual(message, "在线查询暂时失败\n\n只跟踪王者好友")
        self.assertTrue(errors)
        self.query.side_effect = None
        self.assertEqual(self.report([]), ("🐟🐟无人在线\n\n只跟踪王者好友", ""))

    def test_timeout_report_identifies_friend_query_and_safe_response_counts(self):
        from hok_research import QueryTimeout
        self.query.side_effect = QueryTimeout(chunks=[{'private': 'PRIVATE_SENTINEL'}])
        message, errors = ZFUNC.online_process()
        self.assertEqual(message, '在线查询暂时失败\n\n只跟踪王者好友')
        for expected in ('friend_states', 'QueryTimeout', 'response_chunks', 'response_records'):
            self.assertIn(expected, errors)
        self.assertNotIn('PRIVATE_SENTINEL', message + errors)
        self.query.assert_called_once_with('friend_states')
        self.camp.assert_not_called()

    def test_server_stop_keeps_protocol_codes_without_exposing_payload_or_reporting_offline(self):
        from hok_research.apollo import ServerControl
        error = ServerControl(20482, b'')
        error.body = b'PRIVATE_SENTINEL'
        error.error = {'code': 7, 'detail': 14, 'private': 'PRIVATE_SENTINEL'}
        self.query.side_effect = error
        message, errors = ZFUNC.online_process()
        self.assertEqual(message, '在线查询暂时失败\n\n只跟踪王者好友')
        self.assertIn('params={"operation":"friend_states"}', errors)
        self.assertIn(str(ZAPI.player_client_error_info(error)), errors)
        self.assertEqual(ZAPI.player_client_error_info(error),
                         {'type': 'ServerControl', 'command': 20482, 'control_code': 7, 'control_detail': 14})
        self.assertNotIn('PRIVATE_SENTINEL', message + errors)
        self.query.assert_called_once_with('friend_states')
        self.camp.assert_not_called()

    def test_no_bound_main_players_avoids_game_request_and_steam_failures_keep_wzry(self):
        with patch.object(ONLINE, "userlist", {}):
            self.assertEqual(ZFUNC.online_process(), ("🐟🐟无人在线\n\n只跟踪王者好友", ""))
        self.query.assert_not_called()
        with patch.object(ONLINE, "steam_userlist", {"steam": "steam-1"}), \
             patch.dict(ONLINE.confs, {"Steam": {"api_key": "test"}}), \
             patch.object(ZAPI, "steam_api_user_status", side_effect=RuntimeError("unavailable")):
            message, errors = self.report([state(1, "A", game=0)])
        self.assertEqual(message, "在线 1 人\n─────────────\n💤 A\n\n只跟踪王者好友")
        self.assertIn("online.steam_status", errors)


if __name__ == "__main__":
    unittest.main()
