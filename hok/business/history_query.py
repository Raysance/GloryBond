"""Natural-language battle-history query workflow."""

import random

from ..zstatic import *


def _zfunc_call(name, *args, **kwargs):
    from .. import zfunc

    return getattr(zfunc, name)(*args, **kwargs)


def safe_hero_name(*args, **kwargs):
    return _zfunc_call("safe_hero_name", *args, **kwargs)


def _to_pinyin(*args, **kwargs):
    return _zfunc_call("_to_pinyin", *args, **kwargs)


def extract_name(*args, **kwargs):
    return _zfunc_call("extract_name", *args, **kwargs)


def fetch_history(*args, **kwargs):
    return _zfunc_call("fetch_history", *args, **kwargs)


def fetch_battle(*args, **kwargs):
    return _zfunc_call("fetch_battle", *args, **kwargs)


def calculate_battle_contribution_factor(*args, **kwargs):
    return _zfunc_call("calculate_battle_contribution_factor", *args, **kwargs)

def extract_heroname(origin_text,precise=False):
    if txt_contain("轮椅",origin_text,precise,True):
        heroid=-1
        while(True):
            heroid = random.choice(list(HeroList))
            heroname=safe_hero_name(heroid)
            if(heroname in ["狂铁","沈梦溪","海诺","曹操","女娲","艾琳","张飞","嫦娥","元流之子(射手)","艾琳","杨戬","盾山","张飞","云缨"]):break
        return heroid,heroname
    if txt_contain("下水道",origin_text,precise,True):
        heroid=-2
        while(True):
            heroid = random.choice(list(HeroList))
            heroname=safe_hero_name(heroid)
            if(heroname in ["安琪拉","马可波罗","扁鹊","钟无艳","伽罗","孙膑","李元芳","赵怀真","周瑜"]):break
        return heroid,heroname
    for is_origin in [True,False]:
        for heroid,heroname in HeroList.items():
            if txt_contain(heroname,origin_text,precise,is_origin):
                return heroid,heroname
        for heroid,heroname in HeroName_replacements.items():
            if txt_contain(heroname,origin_text,precise,is_origin):
                return heroid,safe_hero_name(heroid)
    return None
def txt_contain(x,y,p,ori):
    if (ori):
        if (p):
            return x == y
        else:
            return x in y
    else:
        y_norm = str(y).lower().replace(' ', '')
        if (p):
            return _to_pinyin(x) == _to_pinyin(y_norm)
        else:
            return _to_pinyin(x) in _to_pinyin(y_norm)

def history_query_handler(rcv_msg):
    from ..zapi import ai_api
    from ..ztime import parse_fuzzy_time, time_r, time_r_delta
    import json
    import re

    user_msg = rcv_msg.strip()
    # 预替换：将用户常用口语/短语映射为规范查询表达，便于后续AI解析
    today_str = time_r().strftime("%Y-%m-%d")
    date_1_days_ago = time_r_delta(1)
    date_1_days_ago_str = date_1_days_ago.strftime("%Y-%m-%d")
    date_2_days_ago = time_r_delta(2)
    date_2_days_ago_str = date_2_days_ago.strftime("%Y-%m-%d")
    date_7_days_ago = time_r_delta(7)
    date_7_days_ago_str = date_7_days_ago.strftime("%Y-%m-%d")
    date_14_days_ago = time_r_delta(14)
    date_14_days_ago_str = date_14_days_ago.strftime("%Y-%m-%d")
    date_30_days_ago = time_r_delta(30)
    date_30_days_ago_str = date_30_days_ago.strftime("%Y-%m-%d")
    alias_map = {
        "带飞": "评分高于",
        "今天": f"{today_str}",
        "昨天": f"{date_1_days_ago_str}",
        "前天": f"{date_2_days_ago_str}",
        "本赛季": f"{this_season_start_date}到{today_str}",
        "这赛季": f"{this_season_start_date}到{today_str}",
        "这个赛季": f"{this_season_start_date}到{today_str}",
        "当前赛季": f"{this_season_start_date}到{today_str}",
        "上个赛季": f"{last_season_start_date}到{last_season_end_date}",
        "上赛季": f"{last_season_start_date}到{last_season_end_date}",
        "上上个赛季": f"{pre_last_season_start_date}到{pre_last_season_end_date}",
        "上上赛季": f"{pre_last_season_start_date}到{pre_last_season_end_date}",
        "这周": f"{date_7_days_ago_str}到{today_str}",
        "本周": f"{date_7_days_ago_str}到{today_str}",
        "上周": f"{date_14_days_ago_str}到{date_7_days_ago_str}",
        "本月": f"{date_30_days_ago_str}到{today_str}",
        "这个月": f"{date_30_days_ago_str}到{today_str}"
    }
    # 优先替换较长键以避免短词匹配冲突
    for k in sorted(alias_map.keys(), key=lambda x: -len(x)):
        if k in user_msg:
            user_msg = user_msg.replace(k, alias_map[k])

    # 具体模式与展示分类共用配置，避免新模式被误解析为成就关键词。
    map_options = [*mapname_replace_rule, "排位赛 单排", "匹配", "娱乐模式"]
    # 引导AI返回结构化数据
    prompt = f"""
    你是一个针对《王者荣耀》战绩历史查询的助手。请从用户的描述中提取查询条件，并返回一个JSON对象。
    支持的字段如下（如果没提到则为null）：
    - PlayerName: 字符串，查询的主体玩家名称。
    - HeroName: 字符串，指用户自己使用的英雄名称。
    - Result: "胜利" 或 "失败"
    - MapName: 字符串，地图/模式名称。已知选项：{json.dumps(map_options, ensure_ascii=False)}。其他明确模式保留原名。共鸣之战等具体模式填入此项，不放入Others。
    - GameTime: 字符串，指游戏开始的具体时间，要求格式"yyyy-mm-dd HH:MM"。
    - FuzzyTime: 字符串，模糊时间描述，如"昨天下午","前天凌晨","上周中午"。
    - DateRange: [start_date, end_date] 字符串数组，格式为 "yyyy-mm-dd"，表示查询的具体日期范围。如果用户提到如 "2024-01-01到2024-02-01" 或类似的明确日期，请填入此项。
    - Position: 整数，分路位置：0为对抗路，1为中路，2为射手/发育路，3为打野，4为辅助。
    - CoPlayers: 数组，同局玩家 [{{"Name": "玩家名", "Hero": "英雄名", "Grade": 评分 }}]。
    - KDA: 数组 [击杀, 死亡, 助攻]。
    - GameGrade: 浮点数，指定具体评分(近似)。
    - Duration: 整数，游戏时长(秒)。
    - Others: 字符串列表，包含 "MVP", "超神", "一血" 等成就关键词，不包含地图/模式名称。

    // 数值区间查询 (支持 "大于8分", "经济20%以上", "承伤30%到40%","伤害25%左右"(左右表示正负3%))
    - GradeRange: [min, max] 浮点数，评分区间。
    - MoneyRange: [min, max] 整数，经济占比(%)区间(0-100)。
    - DamageRange: [min, max] 整数，伤害(对英雄)占比(%)区间(0-100)。
    - DamageTakenRange: [min, max] 整数，承伤占比(%)区间(0-100)。
    - ContributeRange: [min, max] 浮点数，团队贡献系数区间(通常在0.5-2.0之间)。

    // 排名查询 (支持 "评分第一", "全队评分第三")
    - TeamGradeRank: 整数，队内评分排名(1-5)。

    // 比较查询 (如"A的评分比B高", "A的经济/伤害/承伤比B高", "A的贡献比B高")
    // Operator 只支持 ">" (高于) 或 "<" (低于)
    - ScoreComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - MoneyComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - DamageComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - DamageTakenComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - ContributeComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}

    用户描述：{user_msg}
    对于区间，如果只说"大于X"，则为 [X, 100]；"小于X"，则为 [0, X]。
    //以下是玩家名字的示例，请重点关注：
    //{sum(nameref.values(), [])}
    最终只需返回JSON，不要包含任何解释。
    """

    try:
        res_text = ai_api(prompt, temperature=0.1)
        res_text = re.sub(r'```json\n|```', '', res_text).strip()
        query_target = json.loads(res_text)
    except Exception as e:
        return f"查询失败: {str(e)}"

    # 预处理
    # 1. 用extract_name解析玩家名字
    PlayerName=None
    if query_target.get("PlayerName"):
        PlayerName = extract_name(query_target["PlayerName"])
        if PlayerName: query_target["PlayerName"] = PlayerName # 更新为标准化名字


    # 2. 用extract_heroname解析英雄名称
    if query_target.get("HeroName"):
        herores = extract_heroname(query_target["HeroName"])
        if herores: query_target["HeroName"] = herores[1]

    # 3. 解析同局玩家 (名字->RoleId, 英雄名标准化)
    if query_target.get("CoPlayers"):
        for player in query_target["CoPlayers"]:
            # 英雄名标准化
            if player.get("Hero"):
                herores = extract_heroname(player["Hero"])
                if herores: player["Hero"] = herores[1]

            # 玩家名 -> 真实名 -> RoleId
            if player.get("Name"):
                rname = extract_name(player["Name"])
                if rname:
                    player["RealName"] = rname
                    player["Name"] = namenick.get(rname, rname)
                    # 从 roleidlist 获取 RoleId
                    if rname in roleidlist:
                        player["RoleId"] = roleidlist[rname]
                    elif rname in extra_roleidlist:
                        player["RoleId"] = extra_roleidlist[rname]

    # 4. 解析 Comparison 中的名字
    comparison_fields = ["ScoreComparison", "MoneyComparison", "DamageComparison", "DamageTakenComparison", "ContributeComparison"]
    for field in comparison_fields:
        if query_target.get(field):
            sc = query_target[field]
            if sc.get("PlayerA"):
                pn = extract_name(sc["PlayerA"])
                if pn: sc["PlayerA"] = pn

            if sc.get("PlayerB"):
                pn = extract_name(sc["PlayerB"])
                if pn: sc["PlayerB"] = pn

    # 5. 兼容模型将已知模式误放进 Others；其余成就条件继续独立匹配。
    if query_target.get("Others"):
        remaining_others = []
        for keyword in query_target["Others"]:
            if keyword in map_options and query_target.get("MapName") in (None, "", keyword):
                query_target["MapName"] = keyword
            else:
                remaining_others.append(keyword)
        query_target["Others"] = remaining_others

    # MapName 映射逻辑
    map_targets = []
    if query_target.get("MapName"):
        mn = query_target["MapName"]
        if mn == "排位赛":
            map_targets = ["排位赛", "排位赛 双排", "排位赛 三排", "排位赛 五排"]
        elif mn == "排位赛 单排":
            map_targets = ["排位赛"]
        elif mn == "匹配": # 匹配对应到王者峡谷
            map_targets = ["王者峡谷"]
        elif mn in ["娱乐", "娱乐模式"]: # 娱乐模式映射
            map_targets = [mode for mode, category in mapname_replace_rule.items() if category == "娱乐"]
        else:
            map_targets = [mn]

    # 将查询条件转换为自然语言描述
    desc_parts = []
    if query_target.get("PlayerName"):
        nick = namenick.get(query_target["PlayerName"], query_target["PlayerName"])
        desc_parts.append(f"玩家: {nick}")

    if query_target.get("GradeRange"):
        desc_parts.append(f"评分区间: {query_target['GradeRange']}")
    if query_target.get("MoneyRange"):
        desc_parts.append(f"经济: {query_target['MoneyRange']}")
    if query_target.get("DamageRange"):
        desc_parts.append(f"伤害: {query_target['DamageRange']}")
    if query_target.get("DamageTakenRange"):
        desc_parts.append(f"承伤: {query_target['DamageTakenRange']}")
    if query_target.get("ContributeRange"):
        desc_parts.append(f"贡献: {query_target['ContributeRange']}")
    if query_target.get("TeamGradeRank"):
        desc_parts.append(f"评分排名: 第{query_target['TeamGradeRank']}")
    comparison_labels = {
        "ScoreComparison": "评分",
        "MoneyComparison": "经济占比",
        "DamageComparison": "伤害占比",
        "DamageTakenComparison": "承伤占比",
        "ContributeComparison": "贡献"
    }
    for field, label in comparison_labels.items():
        if query_target.get(field):
            sc = query_target[field]
            nickA = namenick.get(sc.get('PlayerA'), sc.get('PlayerA'))
            nickB = namenick.get(sc.get('PlayerB'), sc.get('PlayerB'))
            op = "高于" if sc.get('Operator') == ">" else "低于"
            desc_parts.append(f"{label}比较: {nickA} {op} {nickB}")

    if query_target.get("DateRange"):
        desc_parts.append(f"时间范围: {'到'.join(query_target['DateRange'])}")
    elif query_target.get("FuzzyTime"):

        desc_parts.append(f"模糊时间: {query_target['FuzzyTime']}")
    elif query_target.get("GameTime"):
        desc_parts.append(f"具体时间: {query_target['GameTime']}")

    if query_target.get("HeroName"):
        desc_parts.append(f"英雄: {query_target['HeroName']}")

    if query_target.get("Position") is not None:
        pos_names = ["对抗路", "中路", "发育路", "打野", "辅助"]
        try:
            desc_parts.append(f"分路: {pos_names[int(query_target['Position'])]}")
        except: pass

    if query_target.get("CoPlayers"):
        cp_texts = []
        for p in query_target["CoPlayers"]:
            p_text = f"{p.get('Name','未知')}"
            if p.get('Hero'): p_text += f"({p['Hero']})"
            if p.get('Grade'): p_text += f"[{p['Grade']}分]"
            cp_texts.append(p_text)
        desc_parts.append(f"同局: {', '.join(cp_texts)}")

    if query_target.get("MapName"):
        desc_parts.append(f"地图: {query_target['MapName']}")

    if query_target.get("Result"):
        desc_parts.append(f"结果: {query_target['Result']}")

    if query_target.get("KDA"):
        try:
            k, d, a = query_target["KDA"]
            desc_parts.append(f"KDA约: {k}/{d}/{a}")
        except: pass

    if query_target.get("GameGrade"):
        desc_parts.append(f"评分约: {query_target['GameGrade']}")

    if query_target.get("Duration"):
        try:
            mins = query_target["Duration"] // 60
            secs = query_target["Duration"] % 60
            desc_parts.append(f"时长约: {mins}分{secs}秒")
        except: pass

    if query_target.get("Others"):
        desc_parts.append(f"其他: {' '.join(query_target['Others'])}")

    query_desc = " | ".join(desc_parts) if desc_parts else "全量查询"

    # 至少指定2个条件
    condition_count = 0
    for k, v in query_target.items():
        if k == "CoPlayers" and isinstance(v, list):
            condition_count += len(v)
        elif v:
            condition_count += 1
    if condition_count < 1:
        return [query_target, f"至少指定1个查询条件", query_desc, {}]

    matches = []

    # 解析时间范围
    start_date, end_date = None, None
    fetch_start, fetch_end = None, None
    if query_target.get("DateRange"):
        from ..ztime import str_to_time
        try:
            start_date = str_to_time(query_target["DateRange"][0])
            end_date = str_to_time(query_target["DateRange"][1])
            start_date = start_date.replace(hour=0, minute=0, second=0)
            end_date = end_date.replace(hour=23, minute=59, second=59)
            fetch_start = start_date
            fetch_end = end_date
        except: pass
    elif query_target.get("FuzzyTime"):
        try:
            start_date, end_date = parse_fuzzy_time(query_target["FuzzyTime"])
            # fetch_history 按日期过滤，所以传整天
            fetch_start = start_date.replace(hour=0, minute=0, second=0)
            fetch_end = end_date.replace(hour=23, minute=59, second=59)
        except:
            pass

    # 获取所有玩家的指定时间对局记录
    history_data, _ = fetch_history(start_date=fetch_start, end_date=fetch_end, filter_official=False)

    for realname, details in history_data.items():
        # 如果指定玩家名且不匹配，则continue
        if PlayerName and realname != PlayerName:
            continue

        for detail in details:
            is_match = True
            btl_detail = None
            all_roles = None

            # 英雄名 (_to_pinyin)
            if query_target.get("HeroName"):
                if _to_pinyin(query_target["HeroName"]) not in _to_pinyin(detail.get("HeroName", "")):
                    is_match = False

            # 地图名 (包含匹配与映射)
            if is_match and map_targets:
                if not any(target == detail.get("MapName", "") for target in map_targets):
                    is_match = False

            # 评分区间 (无需详情)
            if is_match and detail.get("GradeMissing") and (query_target.get("GradeRange") or query_target.get("GameGrade")):
                is_match = False
            if is_match and query_target.get("GradeRange"):
               try:
                   grade = float(detail.get("GameGrade", -1))
                   mn, mx = map(float, query_target["GradeRange"])
                   if not (mn <= grade <= mx):
                       is_match = False
               except:
                   is_match = False

            # 分路位置查询 (Position)
            if is_match and query_target.get("Position") is not None:
                btl_detail = fetch_battle(detail["GameSeq"])
                if not btl_detail:
                    is_match = False
                else:
                    target_role_id = roleidlist.get(realname) or extra_roleidlist.get(realname)
                    my_role = None
                    all_roles = btl_detail.get('redRoles', []) + btl_detail.get('blueRoles', [])
                    for role in all_roles:
                        if str(role.get('basicInfo', {}).get('roleId', '')) == str(target_role_id):
                            my_role = role
                            break
                    if my_role:
                        if int(my_role.get('battleRecords', {}).get('position', -1)) != int(query_target['Position']):
                            is_match = False
                    else:
                        is_match = False

            btl_detail = btl_detail if 'btl_detail' in locals() and btl_detail else None
            all_roles = all_roles if 'all_roles' in locals() and all_roles else None

            # ------------------------------------------------------------------
            # (1) 同局玩家查询 (CoPlayers)
            # ------------------------------------------------------------------
            if is_match and query_target.get("CoPlayers"):
                btl_detail = fetch_battle(detail["GameSeq"])
                if (not btl_detail): # 由于从1月份才开始保存battle_info
                    is_match = False # 如果指定了队友/对手，并且对局记录不存在，则直接忽略该对局
                else:
                    # 获取红蓝双方所有玩家
                    all_roles = btl_detail.get('redRoles', []) + btl_detail.get('blueRoles', [])

                    found_all_coplayers = True
                    for target_p in query_target["CoPlayers"]:
                        found_this = False
                        for role in all_roles:
                            # 1. 名字/RoleId 匹配
                            if target_p.get("RoleId"):
                                if str(role.get('basicInfo', {}).get('roleId', '')) != str(target_p["RoleId"]):
                                    continue
                            elif target_p.get("Name"):
                                role_name = role.get('basicInfo', {}).get('roleName', '')
                                if target_p["Name"] not in role_name:
                                    continue

                            # 2. 英雄匹配 (已标准化)
                            used_hero = role.get('battleRecords', {}).get('usedHero', {}).get('heroName', '')
                            if target_p.get("Hero"):
                                # 此处使用标准化后的名称进行对比，所以用精确匹配或拼音匹配
                                if _to_pinyin(target_p["Hero"]) not in _to_pinyin(used_hero):
                                    # 再尝试一下模糊包含
                                    if not txt_contain(target_p["Hero"], used_hero, False, False):
                                        continue

                            # 3. 评分匹配 (误差0.5以内)
                            if target_p.get("Grade"):
                                try:
                                    role_grade = float(role.get('battleStats', {}).get('gradeGame', -1))
                                    target_grade = float(target_p["Grade"])
                                    if abs(role_grade - target_grade) > 0.5:
                                        continue
                                except:
                                    continue

                            found_this = True
                            break

                        if not found_this:
                            found_all_coplayers = False
                            break

                    if not found_all_coplayers:
                        is_match = False

            # ------------------------------------------------------------------
            # (2) 详细数据查询 (Money, Damage, Rank, Comparison)
            # ------------------------------------------------------------------
            need_advanced_stats = (
                query_target.get("MoneyRange") or
                query_target.get("DamageRange") or
                query_target.get("DamageTakenRange") or
                query_target.get("ContributeRange") or
                query_target.get("TeamGradeRank") or
                query_target.get("ScoreComparison") or
                query_target.get("MoneyComparison") or
                query_target.get("DamageComparison") or
                query_target.get("DamageTakenComparison") or
                query_target.get("ContributeComparison")
            )

            if is_match and need_advanced_stats:
                if not btl_detail:
                    btl_detail = fetch_battle(detail["GameSeq"])
                if btl_detail:
                    all_roles = btl_detail.get('redRoles', []) + btl_detail.get('blueRoles', [])

                if (not btl_detail):
                    is_match = False
                else:
                    # 找到自己的Role (用于后续统计)
                    my_role = None
                    target_role_id = roleidlist.get(realname)
                    if target_role_id:
                        for r in all_roles:
                             if str(r.get("basicInfo",{}).get("roleId")) == str(target_role_id):
                                 my_role = r
                                 break

                    if is_match and my_role:
                        my_camp = my_role.get("basicInfo", {}).get("acntCamp")
                        team_roles = [r for r in all_roles if r.get("basicInfo", {}).get("acntCamp") == my_camp]

                        stats = my_role.get("battleStats", {})

                        # 经济占比区间
                        if query_target.get("MoneyRange"):
                            # try:
                            total_money = sum(float(r.get("battleStats", {}).get("money", 0)) for r in team_roles)
                            my_val = float(stats.get("money", 0))
                            percent = (my_val / total_money * 100) if total_money > 0 else 0
                            mn, mx = map(float, query_target["MoneyRange"])
                            if not (mn <= percent <= mx): is_match = False
                            # except: is_match = False

                        # 伤害占比区间
                        if is_match and query_target.get("DamageRange"):
                            # try:
                            total_hurt = sum(float(r.get("battleStats", {}).get("totalHeroHurtCnt", 0)) for r in team_roles)
                            my_val = float(stats.get("totalHeroHurtCnt", 0))
                            percent = (my_val / total_hurt * 100) if total_hurt > 0 else 0
                            mn, mx = map(float, query_target["DamageRange"])
                            if not (mn <= percent <= mx): is_match = False
                            # except: is_match = False

                        # 承伤占比区间
                        if is_match and query_target.get("DamageTakenRange"):
                            # try:
                            total_behurt = sum(float(r.get("battleStats", {}).get("totalBeheroHurtCnt", 0)) for r in team_roles)
                            my_val = float(stats.get("totalBeheroHurtCnt", 0))
                            percent = (my_val / total_behurt * 100) if total_behurt > 0 else 0
                            mn, mx = map(float, query_target["DamageTakenRange"])
                            if not (mn <= percent <= mx): is_match = False
                            # except: is_match = False

                        # 贡献度系数区间
                        if is_match and query_target.get("ContributeRange"):
                            try:
                                factor = calculate_battle_contribution_factor(btl_detail, role=my_role)
                                if factor is not None:
                                    mn, mx = map(float, query_target["ContributeRange"])
                                    if not (mn <= factor <= mx): is_match = False
                                else:
                                    is_match = False
                            except: is_match = False

                        # 队内评分排名
                        if is_match and query_target.get("TeamGradeRank"):
                            try:
                                my_grade = float(my_role.get("battleStats", {}).get("gradeGame", -1))
                                my_rank = 1
                                for r in team_roles:
                                    if str(r.get("basicInfo", {}).get("roleId")) == str(my_role.get("basicInfo", {}).get("roleId")):
                                        continue
                                    if float(r.get("battleStats", {}).get("gradeGame", -1)) > my_grade:
                                        my_rank += 1

                                target_rank = int(query_target["TeamGradeRank"])
                                if my_rank != target_rank:
                                    is_match = False
                            except: is_match = False

                    # 属性比较
                    if is_match:
                        def get_role_by_name(p_name):
                            rid = roleidlist.get(p_name) or extra_roleidlist.get(p_name)
                            for r in all_roles:
                                if rid:
                                    if str(r.get("basicInfo",{}).get("roleId")) == str(rid):
                                        return r
                                elif p_name and p_name in r.get("basicInfo", {}).get("roleName", ""):
                                    return r
                            return None

                        def get_stat_value(role, field_name):
                            stats = role.get("battleStats", {})
                            if field_name == "ScoreComparison":
                                return float(stats.get("gradeGame", -1))

                            # 获取队伍总和
                            camp = role.get("basicInfo", {}).get("acntCamp")
                            t_roles = [x for x in all_roles if x.get("basicInfo", {}).get("acntCamp") == camp]

                            if field_name == "MoneyComparison":
                                total = sum(float(x.get("battleStats", {}).get("money", 0)) for x in t_roles)
                                return (float(stats.get("money", 0)) / total * 100) if total > 0 else 0
                            elif field_name == "DamageComparison":
                                total = sum(float(x.get("battleStats", {}).get("totalHeroHurtCnt", 0)) for x in t_roles)
                                return (float(stats.get("totalHeroHurtCnt", 0)) / total * 100) if total > 0 else 0
                            elif field_name == "DamageTakenComparison":
                                total = sum(float(x.get("battleStats", {}).get("totalBeheroHurtCnt", 0)) for x in t_roles)
                                return (float(stats.get("totalBeheroHurtCnt", 0)) / total * 100) if total > 0 else 0
                            elif field_name == "ContributeComparison":
                                return calculate_battle_contribution_factor(btl_detail, role=role) or 0
                            return -1

                        comp_fields = ["ScoreComparison", "MoneyComparison", "DamageComparison", "DamageTakenComparison", "ContributeComparison"]
                        for field in comp_fields:
                            if is_match and query_target.get(field):
                                try:
                                    sc = query_target[field]
                                    pa, pb, op = sc.get("PlayerA"), sc.get("PlayerB"), sc.get("Operator")
                                    roleA, roleB = get_role_by_name(pa), get_role_by_name(pb)

                                    if roleA and roleB:
                                        valA = get_stat_value(roleA, field)
                                        valB = get_stat_value(roleB, field)

                                        if op == ">" and not (valA > valB): is_match = False
                                        elif op == "<" and not (valA < valB): is_match = False
                                    else: is_match = False
                                except: is_match = False

            # 输赢
            if is_match and query_target.get("Result"):
                if query_target["Result"] not in detail.get("Result", ""):
                    is_match = False

            # KDA (略微近似, 每个值差值<=1)
            if is_match and query_target.get("KDA"):
                try:
                    tk, td, ta = query_target["KDA"]
                    dk, dd, da = detail.get("KillCnt", 0), detail.get("DeadCnt", 0), detail.get("AssistCnt", 0)
                    if abs(int(tk) - int(dk)) > 1 or abs(int(td) - int(dd)) > 1 or abs(int(ta) - int(da)) > 1:
                        is_match = False
                except:
                    pass

            # 评分 (略微近似, 差值<=0.5)
            if is_match and query_target.get("GameGrade"):
                try:
                    if abs(float(detail.get("GameGrade", 0)) - float(query_target["GameGrade"])) > 0.5:
                        is_match = False
                except:
                    pass

            # 时长 (略微近似, 差值<=60s)
            if is_match and query_target.get("Duration"):
                try:
                    if abs(int(detail.get("Duration_Second", 0)) - int(query_target["Duration"])) > 60:
                        is_match = False
                except:
                    pass

            # 游戏时间 (支持 30 分钟偏差)
            if is_match and query_target.get("GameTime"):
                t_time_str = str(query_target["GameTime"])
                match_time = re.search(r'(\d{1,2}:\d{1,2})', t_time_str)
                if match_time:
                    t_hhmm = match_time.group(1)
                    d_time_str = str(detail.get("GameTime", ""))
                    match_time_d = re.search(r'(\d{1,2}:\d{1,2})', d_time_str)

                    if match_time_d:
                        d_hhmm = match_time_d.group(1)
                        try:
                            th, tm = map(int, t_hhmm.split(":"))
                            dh, dm = map(int, d_hhmm.split(":"))
                            diff = abs((th * 60 + tm) - (dh * 60 + dm))
                            if diff > 12 * 60:
                                diff = 24 * 60 - diff

                            if diff > 30:
                                is_match = False
                        except:
                            if t_hhmm not in d_time_str:
                                is_match = False
                    elif t_hhmm not in d_time_str:
                        is_match = False

            # 如果有 FuzzyTime, 还需要额外过滤具体时间点 (fetch_history 只按日期过滤)
            if is_match and start_date and end_date:
                detail_time_str = str(detail.get("GameTime", ""))
                if detail_time_str:
                    try:
                        from ..ztime import datetime_from_parts
                        # 尝试匹配完整日期格式 yyyy-mm-dd HH:MM
                        full_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{1,2})', detail_time_str)
                        current_detail_dt = None

                        if full_match:
                            y, m, d, H, M = map(int, full_match.groups())
                            current_detail_dt = datetime_from_parts(y, m, d, H, M)
                        else:
                            # 尝试匹配 HH:MM
                            time_match = re.search(r'(\d{1,2}):(\d{1,2})', detail_time_str)
                            if time_match:
                                dt_h, dt_m = map(int, time_match.groups())
                                current_detail_dt = start_date.replace(hour=dt_h, minute=dt_m)

                        if current_detail_dt:
                            if not (start_date <= current_detail_dt <= end_date):
                                is_match = False
                    except:
                        pass

            # Others (MVP/超神/一血)
            if is_match and query_target.get("Others"):
                d_others = detail.get("Others") or ""
                for keyword in query_target["Others"]:
                    if keyword not in d_others:
                        is_match = False
                        break

            if is_match:
                matches.append([detail, realname])

    # 去重: 对于gameseq相同的对局只保留一份
    unique_matches = []
    seen_gameseqs = set()
    for m in matches:
        # m[0] is detail
        gs = str(m[0].get("GameSeq") or "")
        if gs and gs not in seen_gameseqs:
            seen_gameseqs.add(gs)
            unique_matches.append(m)
    matches = unique_matches

    # 统计数据
    stats = {}
    if matches:
        total = len(matches)
        wins = sum(1 for m, _ in matches if "胜利" in m.get("Result", ""))
        scored = [m for m, _ in matches if not m.get("GradeMissing") and m.get("GameGrade") is not None]
        total_grade = sum(float(m["GameGrade"]) for m in scored)
        total_k = sum(int(m.get("KillCnt", 0)) for m, _ in matches)
        total_d = sum(int(m.get("DeadCnt", 0)) for m, _ in matches)
        total_a = sum(int(m.get("AssistCnt", 0)) for m, _ in matches)

        stats = {
            "total": total,
            "wins": wins,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "avg_grade": (total_grade / len(scored)) if scored else 0,
            "score_count": len(scored),
            "total_k": total_k,
            "total_d": total_d,
            "total_a": total_a,
            "avg_kda": (total_k + total_a) / max(total_d, 1)
        }

    return [query_target, matches, query_desc, stats]


def format_history_query_prefix(query_desc, stats):
    prefix = f"🔍查询条件：{query_desc}\n\n"
    if not stats:
        return prefix

    total = stats.get("total", 0)
    prefix += f"📊 统计概览 ({total}场)：\n"
    prefix += (
        f"胜率: {stats.get('win_rate', 0):.1f}% "
        f"({stats.get('wins', 0)}胜{total - stats.get('wins', 0)}负)\n"
    )
    grade_label = f"{stats.get('avg_grade', 0):.1f}" if stats.get("score_count", total) else "—"
    prefix += f"平均评分: {grade_label}\n"
    prefix += (
        f"场均KDA: {stats.get('total_k', 0) / total:.1f}/"
        f"{stats.get('total_d', 0) / total:.1f}/"
        f"{stats.get('total_a', 0) / total:.1f} "
        f"({stats.get('avg_kda', 0):.2f})\n\n"
    )
    return prefix


def pack_history_query_matches(matches, role_ids, battle_loader):
    packed_data = []
    for detail, realname in matches:
        gameseq = detail["GameSeq"]
        roleid = role_ids[realname]
        battle_res = battle_loader(gameseq)

        nickname = ""
        if battle_res:
            roles = battle_res.get("redRoles", []) + battle_res.get("blueRoles", [])
            for role in roles:
                if str(role["basicInfo"].get("roleId")) == str(roleid):
                    nickname = role["basicInfo"]["roleName"]
                    break

        packed_data.append(
            {
                "realname": realname,
                "Nickname": nickname,
                "roleId": roleid,
                "GameTime": detail.get("GameTime_Timestamp"),
                "Duration": detail.get("Duration_Second"),
                "HeroName": detail.get("HeroName"),
                "MapName": detail.get("MapName"),
                "KillCnt": detail.get("KillCnt"),
                "DeadCnt": detail.get("DeadCnt"),
                "AssistCnt": detail.get("AssistCnt"),
                "Result": detail.get("Result"),
                "GameGrade": None if detail.get("GradeMissing") else detail.get("GameGrade"),
                "GradeMissing": bool(detail.get("GradeMissing")),
                "GameSeq": str(gameseq) if detail.get("Source") == "player_client" else gameseq,
                "Source": detail.get("Source"),
                "Params": detail.get("Params") or {},
                "Others": detail.get("Others"),
            }
        )
    return packed_data
