"""Legacy AI prompt assembly and adapter selection."""

from .. import zdynamic as dmc
from .. import zapi, ztime
from ..chat_roles import build_role_prompt
from ..zstatic import *


def ai_parser(user_query,msg_type,network=False,use_mem=None):
    if use_mem is None:
        use_mem = dmc.use_mem

    ai_temperature=1.5
    style_templates_index=ztime.get_timebased_rand(len(pmpt_style_templates),30)
    style_template=pmpt_style_templates[style_templates_index]
    
    whole_query=""

    match msg_type:
        case "rnk":
            whole_query += remind_news_pmpt + dmc.today_news + rnk_pmpt + user_query[0]
        case "best_battle":
            whole_query += "你是一个幽默的王者荣耀解说，请用夸张、幽默且具有生活气息的语言，对以下这局今日最有代表性的对局进行一句话点评（70字以内，不用双引号，不用Markdown）：" + user_query[0]
        case "single_parser":
            whole_query += name_pmpt[0] + str(nameref) + name_pmpt[1]+ user_query[0] + name_pmpt[2]
            ai_temperature=2
        case "single_player":
            whole_query += single_pmpt1 + user_query[0] + user_query[1] + single_pmpt2 + user_query[2]
        case "tq":
            whole_query += tq_pmpt + user_query[0]
        case "chat":
            role_prompt = build_role_prompt(chat_role)
            if use_mem:
                context_msg = f"""
                【情境信息】
                - 当前用户: {user_query[2]} (QID: {user_query[3]})
                
                - 当前用户与 Bot 的近期直接对话（仅来自 chat event）:
                {user_query[1]}
                
                【重要指令】
                以上信息仅作为对话背景。
                只使用当前用户此前直接对 Bot 说过的话和 Bot 对该用户的回复延续语境。
                不要假设其中包含其他用户的发言、群聊旁观内容、提炼总结或其他来源的记忆。
                请自然地融合在回复中，不要直接提及“记忆模块”“系统提示”等内部实现。
                
                当前请求: {user_query[0]}
                """
                whole_query += role_prompt + style_template + context_msg + chat_pmpt
            else:
                whole_query += role_prompt + style_template + "这是这次的请求：（" + user_query[0] + "）" + chat_pmpt + "回答中不用透露出现有记住/记录这些，自然一些,并保持礼貌文明用语。"
        case "poke":
            whole_query = poke_pmpt[0] + user_query[0] + poke_pmpt[1] + user_query[1] + poke_pmpt[2]
        case "battle_lineup":
            whole_query = battle_lineup_pmpt + user_query[0]
        case "festival":
            whole_query = festival_pmpt[0] + user_query[0] + festival_pmpt[1]
        case "raise_question":
            whole_query = raise_question_pmpte
        case "pure_chat":
            whole_query = user_query[0]
        case "urge_game":
            whole_query = urge_game_pmpt[0] + user_query[0] + urge_game_pmpt[1] + user_query[1] + urge_game_pmpt[2] + user_query[2] + urge_game_pmpt[3]
        case "summary":
            whole_query = user_query[0]
        case "skill_advantage":
            whole_query = skill_advantage_pmpt[0] + skill_advantage_pmpt[1] + user_query[0] + skill_advantage_pmpt[2] + user_query[1] +  skill_advantage_pmpt[3] + user_query[2] + skill_advantage_pmpt[4] + user_query[3] + skill_advantage_pmpt[5] + user_query[4]
    ai_back=""
    ai_status=True
    if (not network):
        try:
            ai_back=zapi.ai_api(user_query=whole_query,temperature=ai_temperature)
        except Exception as e:
            ai_status=False
            ai_back=str(e)
    else:
        try:
            whole_query=ark_chat_pmpt+whole_query
            ai_back=zapi.ark_api(whole_query)
        except Exception as e:
            ai_status=False
            ai_back=str(e)

    return ai_back

