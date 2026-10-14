"""Steam Web API adapters."""

from .proxy import clash_request

def steam_api_user_status(api_key, steam_id):
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    params = {
        'key': api_key,
        'steamids': steam_id
    }

    response = clash_request("GET", url, params=params, timeout=20)
    data = response.json()

    players = data.get('response', {}).get('players', [])
    if players:
        player = players[0]
        return player
    return {}
def steam_api_recent_games(api_key, steam_id):
    """
    获取指定用户最近14天玩过的游戏及总时长
    :param api_key: 你的 Steam Web API Key
    :param steam_id: 目标用户的 64位 SteamID
    """
    url = "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
    params = {
        'key': api_key,
        'steamid': steam_id,
        'format': 'json'
    }

    try:
        response = clash_request("GET", url, params=params, timeout=20)
        response.raise_for_status()  # 检查 HTTP 状态码
        data = response.json()

        # 获取游戏列表
        games = data.get('response', {}).get('games', [])

        return games

        # game_info = {
        #     'name': game.get('name'),
        #     'appid': game.get('appid'),
        #     'playtime_2weeks': game.get('playtime_2weeks'), # 最近两周时长（分钟）
        #     'playtime_forever': game.get('playtime_forever') # 历史总时长（分钟）
        # }


    except Exception as e:
        raise Exception("STEAM Exception: "+str(e))
