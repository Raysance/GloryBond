"""JSON-grounded scoring helpers for selecting a representative battle."""


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, float(value)))


def _rising_ratio(value, start, full):
    """Return 0 at/below start and 1 at/above full."""
    start = _number(start)
    full = _number(full)
    if full <= start:
        return 0.0
    return _clamp((_number(value) - start) / (full - start))


def _falling_ratio(value, start, full):
    """Return 0 at/above start and 1 at/below full."""
    start = _number(start)
    full = _number(full)
    if full >= start:
        return 0.0
    return _clamp((start - _number(value)) / (start - full))


def _display_number(value):
    value = round(float(value), 2)
    return int(value) if value.is_integer() else value


def _contains_keyword(text, keyword):
    return str(keyword).casefold() in str(text).casefold()


def build_battle_keywords(game):
    """Normalize only verified btlist JSON fields used by the scorer."""
    keywords = []

    if _number(game.get("mvpcnt")) + _number(game.get("losemvp")) >= 1:
        keywords.append("MVP")
    if _number(game.get("firstBlood")) > 0:
        keywords.append("一血")
    if _number(game.get("godLikeCnt")) > 0:
        keywords.append("超神")

    multi_kill_sources = [
        ("十杀", ("hero1Kill10Cnt",)),
        ("九杀", ("hero1Kill9Cnt",)),
        ("八杀", ("hero1Kill8Cnt",)),
        ("七杀", ("hero1Kill7Cnt", "sevenKill")),
        ("六杀", ("hero1Kill6Cnt", "sixKill")),
        ("五连绝世", ("hero1RampageCnt", "rampage")),
        ("四连超凡", ("hero1UltraKillCnt",)),
        ("三连决胜", ("hero1TripleKillCnt",)),
    ]
    for keyword, fields in multi_kill_sources:
        if any(_number(game.get(field)) > 0 for field in fields):
            keywords.append(keyword)
            break

    return " ".join(keywords)


def validate_candidate(battle, rules):
    """Return (eligible, reasons) for configuration-driven hard filters."""
    eligibility = rules.get("eligibility", {})
    reasons = []
    result = battle.get("Result")
    grade = _number(battle.get("GameGrade"))
    duration = _number(battle.get("Duration_Second"))

    if not battle.get("GameSeq"):
        reasons.append("缺少GameSeq")
    if result not in eligibility.get("valid_results", ["胜利", "失败"]):
        reasons.append(f"结果无效:{result}")
    if grade < _number(eligibility.get("min_grade", 0)):
        reasons.append(f"评分低于{eligibility.get('min_grade')}")
    if grade > _number(eligibility.get("max_grade", 20)):
        reasons.append(f"评分高于{eligibility.get('max_grade')}")
    if duration < _number(eligibility.get("min_duration_seconds", 0)):
        reasons.append(f"时长低于{eligibility.get('min_duration_seconds')}秒")
    if duration > _number(eligibility.get("max_duration_seconds", 7200)):
        reasons.append(f"时长高于{eligibility.get('max_duration_seconds')}秒")
    return not reasons, reasons


def _role_id(role):
    return role.get("roleId", role.get("basicInfo", {}).get("roleId"))


def _role_camp(role):
    return role.get("acntCamp", role.get("basicInfo", {}).get("acntCamp"))


def _stats_value(stats, *fields):
    for field in fields:
        if field in stats and stats.get(field) is not None:
            return _number(stats.get(field))
    return 0.0


def _team_total(roles, *fields):
    return sum(_stats_value(role.get("battleStats", {}), *fields) for role in roles)


def _detail_context(detail, roleid):
    if not isinstance(detail, dict) or "head" not in detail:
        return None

    red_roles = detail.get("redRoles") or []
    blue_roles = detail.get("blueRoles") or []
    all_roles = red_roles + blue_roles
    target_role = next((role for role in all_roles if str(_role_id(role)) == str(roleid)), None)
    if not target_role:
        return None

    my_camp = _role_camp(target_role)
    red_camp = detail.get("redTeam", {}).get("acntCamp")
    if red_camp is None and red_roles:
        red_camp = _role_camp(red_roles[0])
    if my_camp is None or red_camp is None:
        return None

    my_team = red_roles if str(my_camp) == str(red_camp) else blue_roles
    enemy_team = blue_roles if my_team is red_roles else red_roles
    if not my_team or not enemy_team:
        return None

    return {
        "my_role": target_role,
        "my_stats": target_role.get("battleStats", {}),
        "my_team": my_team,
        "enemy_team": enemy_team,
    }


def _multi_kill_level(others, my_stats):
    detail_levels = [
        (10, "tenKillCnt"),
        (9, "nineKillCnt"),
        (8, "eightKillCnt"),
        (7, "sevenKillCnt"),
        (6, "sixKillCnt"),
        (5, "rampageCnt"),
        (4, "UltraKillCnt"),
        (3, "tripleKillCnt"),
    ]
    for level, field in detail_levels:
        if _stats_value(my_stats, field) > 0:
            return level, f"battleStats.{field}>0"

    summary_levels = [
        (10, "十杀"),
        (9, "九杀"),
        (8, "八杀"),
        (7, "七杀"),
        (6, "六杀"),
        (5, "五连绝世"),
        (4, "四连超凡"),
        (3, "三连决胜"),
    ]
    for level, keyword in summary_levels:
        if _contains_keyword(others, keyword):
            return level, f"Others包含“{keyword}”"
    return 0, ""


def score_candidate(battle, detail, roleid, rules):
    """Calculate comparable 0-100 good, bad and extreme indices."""
    category_rules = rules.get("categories", {})
    category_order = ["good", "bad", "extreme"]
    scores = {category: 0.0 for category in category_order}
    breakdowns = {category: [] for category in category_order}
    detail_metrics = {}

    def add(category, rule, ratio, condition, source):
        ratio = _clamp(ratio)
        if ratio <= 0:
            return
        contribution = _number(rule.get("weight")) * ratio
        scores[category] += contribution
        breakdowns[category].append({
            "factor": rule.get("label"),
            "contribution": _display_number(contribution),
            "max_weight": _display_number(rule.get("weight")),
            "ratio": round(ratio, 4),
            "condition": condition,
            "source": source,
        })

    grade = _number(battle.get("GameGrade"))
    result = battle.get("Result")
    others = str(battle.get("Others") or "")
    duration = _number(battle.get("Duration_Second"))
    kills = int(_number(battle.get("KillCnt")))
    deaths = int(_number(battle.get("DeadCnt")))
    assists = int(_number(battle.get("AssistCnt")))
    context = _detail_context(detail, roleid)
    my_stats = context["my_stats"] if context else {}
    if "kda" in my_stats:
        kda = _number(my_stats.get("kda"))
        kda_source = "battleStats.kda"
    else:
        kda = (kills + assists) / max(1, deaths)
        kda_source = "(KillCnt+AssistCnt)/max(1,DeadCnt)"

    good = category_rules.get("good", {}).get("factors", {})
    bad = category_rules.get("bad", {}).get("factors", {})
    extreme = category_rules.get("extreme", {}).get("factors", {})

    rule = good.get("absolute_grade", {})
    add("good", rule, _rising_ratio(grade, rule.get("start"), rule.get("full")), f"GameGrade={grade}", "摘要JSON")

    rule = bad.get("absolute_grade", {})
    add("bad", rule, _falling_ratio(grade, rule.get("start"), rule.get("full")), f"GameGrade={grade}", "摘要JSON")

    rule = good.get("kda", {})
    add("good", rule, _rising_ratio(kda, rule.get("start"), rule.get("full")), f"{kda_source}={round(kda, 2)}", "JSON")

    rule = bad.get("kda", {})
    add("bad", rule, _falling_ratio(kda, rule.get("start"), rule.get("full")), f"{kda_source}={round(kda, 2)}", "JSON")

    rule = bad.get("deaths", {})
    add("bad", rule, _rising_ratio(deaths, rule.get("start"), rule.get("full")), f"DeadCnt={deaths}", "摘要JSON")

    duration_rule = extreme.get("duration", {})
    long_ratio = _rising_ratio(
        duration,
        duration_rule.get("long_start_seconds"),
        duration_rule.get("long_full_seconds"),
    )
    short_ratio = _falling_ratio(
        duration,
        duration_rule.get("short_start_seconds"),
        duration_rule.get("short_full_seconds"),
    )
    if long_ratio >= short_ratio and long_ratio > 0:
        add(
            "extreme",
            {"label": duration_rule.get("long_label"), "weight": duration_rule.get("weight")},
            long_ratio,
            f"Duration_Second={int(duration)}",
            "摘要JSON",
        )
    elif short_ratio > 0:
        add(
            "extreme",
            {"label": duration_rule.get("short_label"), "weight": duration_rule.get("weight")},
            short_ratio,
            f"Duration_Second={int(duration)}",
            "摘要JSON",
        )

    is_mvp = _contains_keyword(others, "MVP") or _stats_value(my_stats, "mvp") > 0
    is_godlike = _contains_keyword(others, "超神") or _stats_value(my_stats, "godLikeCnt") > 0
    is_first_blood = _contains_keyword(others, "一血")
    multi_level, multi_condition = _multi_kill_level(others, my_stats)

    if is_mvp:
        add("good", good.get("mvp", {}), 1, "MVP标记为真", "JSON标记")
    if multi_level:
        multi_rule = good.get("multi_kill", {})
        ratio = _number(multi_rule.get("levels", {}).get(str(multi_level), 0))
        multi_labels = {
            3: "三连决胜",
            4: "四连超凡",
            5: "五连绝世",
            6: "六杀",
            7: "七杀",
            8: "八杀",
            9: "九杀",
            10: "十杀",
        }
        display_rule = dict(multi_rule)
        display_rule["label"] = multi_labels[multi_level]
        add("good", display_rule, ratio, f"{multi_condition}，多杀级别={multi_level}", "JSON标记")
    if is_godlike:
        add("good", good.get("godlike", {}), 1, "超神标记为真", "JSON标记")
    if is_first_blood:
        add("good", good.get("first_blood", {}), 1, "一血标记为真", "JSON标记")

    if context:
        my_role = context["my_role"]
        my_team = context["my_team"]
        enemy_team = context["enemy_team"]
        my_team_grade = _team_total(my_team, "gradeGame")
        enemy_team_grade = _team_total(enemy_team, "gradeGame")
        my_detail_grade = _number(my_stats.get("gradeGame", grade))
        teammate_grades = [
            _stats_value(role.get("battleStats", {}), "gradeGame")
            for role in my_team
            if role is not my_role
        ]
        if teammate_grades:
            teammate_average_grade = sum(teammate_grades) / len(teammate_grades)
            teammate_highest_grade = max(teammate_grades)
            teammate_lowest_grade = min(teammate_grades)
            high_relative_ratio = 0.0
            low_relative_ratio = 0.0

            if my_detail_grade > teammate_average_grade:
                denominator = teammate_average_grade - teammate_highest_grade
                high_relative_ratio = (
                    1.0
                    if abs(denominator) < 1e-9
                    else _clamp((teammate_average_grade - my_detail_grade) / denominator)
                )
            elif my_detail_grade < teammate_average_grade:
                denominator = teammate_average_grade - teammate_lowest_grade
                low_relative_ratio = (
                    1.0
                    if abs(denominator) < 1e-9
                    else _clamp((teammate_average_grade - my_detail_grade) / denominator)
                )

            detail_metrics.update({
                "TeammateAverageGrade": round(teammate_average_grade, 2),
                "TeammateHighestGrade": round(teammate_highest_grade, 2),
                "TeammateLowestGrade": round(teammate_lowest_grade, 2),
                "HighRelativeGradePercent": round(high_relative_ratio * 100, 2),
                "LowRelativeGradePercent": round(low_relative_ratio * 100, 2),
            })

            rule = good.get("relative_grade", {})
            add(
                "good",
                rule,
                high_relative_ratio,
                (
                    f"(队友均分{round(teammate_average_grade, 2)}-自己{round(my_detail_grade, 2)})/"
                    f"(队友均分{round(teammate_average_grade, 2)}-队友最高{round(teammate_highest_grade, 2)})"
                    f"={round(high_relative_ratio * 100, 2)}%"
                ),
                "详情JSON",
            )

            rule = bad.get("relative_grade", {})
            add(
                "bad",
                rule,
                low_relative_ratio,
                (
                    f"(队友均分{round(teammate_average_grade, 2)}-自己{round(my_detail_grade, 2)})/"
                    f"(队友均分{round(teammate_average_grade, 2)}-队友最低{round(teammate_lowest_grade, 2)})"
                    f"={round(low_relative_ratio * 100, 2)}%"
                ),
                "详情JSON",
            )

        team_damage = _team_total(my_team, "totalHeroHurtCnt")
        team_taken = _team_total(my_team, "totalBeheroHurtCnt")
        team_gold = _team_total(my_team, "money")
        hero_damage = _stats_value(my_stats, "totalHeroHurtCnt")
        damage_taken = _stats_value(my_stats, "totalBeheroHurtCnt")
        gold = _stats_value(my_stats, "money")
        damage_percent = hero_damage / team_damage * 100 if team_damage else 0
        taken_percent = damage_taken / team_taken * 100 if team_taken else 0
        gold_percent = gold / team_gold * 100 if team_gold else 0
        detail_metrics.update({
            "DamagePercent": round(damage_percent, 2),
            "TakenPercent": round(taken_percent, 2),
            "GoldPercent": round(gold_percent, 2),
        })

        rule = good.get("damage_share", {})
        add(
            "good",
            rule,
            _rising_ratio(damage_percent, rule.get("start_percent"), rule.get("full_percent")),
            f"输出占比={round(damage_percent, 2)}%",
            "详情JSON",
        )

        rule = good.get("taken_share", {})
        add(
            "good",
            rule,
            _rising_ratio(taken_percent, rule.get("start_percent"), rule.get("full_percent")),
            f"承伤占比={round(taken_percent, 2)}%",
            "详情JSON",
        )

        direct_participation = _stats_value(my_stats, "joinGamePercent")
        if direct_participation > 0:
            participation = direct_participation * 100 if direct_participation <= 1 else direct_participation
        else:
            team_kills = _team_total(my_team, "killCnt")
            participation = (kills + assists) / team_kills * 100 if team_kills else 0
        detail_metrics["ParticipationPercent"] = round(participation, 2)

        rule = good.get("participation", {})
        add(
            "good",
            rule,
            _rising_ratio(participation, rule.get("start_percent"), rule.get("full_percent")),
            f"参团率={round(participation, 2)}%",
            "详情JSON",
        )

        contribution_percent = max(damage_percent, taken_percent)
        efficiency = contribution_percent / gold_percent if gold_percent else 0
        detail_metrics["Efficiency"] = round(efficiency, 3)
        if gold_percent > 0:
            rule = bad.get("low_efficiency", {})
            add(
                "bad",
                rule,
                _falling_ratio(efficiency, rule.get("start"), rule.get("full")),
                f"max(输出占比,承伤占比)/经济占比={round(efficiency, 3)}",
                "详情JSON",
            )

        grade_diff = enemy_team_grade - my_team_grade
        detail_metrics["TeamGradeGap"] = round(grade_diff, 2)
        contradiction = extreme.get("result_grade_contradiction", {})
        if result == "胜利" and grade_diff > 0:
            add(
                "extreme",
                {"label": contradiction.get("win_label"), "weight": contradiction.get("weight")},
                _rising_ratio(grade_diff, contradiction.get("start_gap"), contradiction.get("full_gap")),
                f"胜利且敌方团队总评分-我方={round(grade_diff, 2)}",
                "详情JSON",
            )
        elif result == "失败" and grade_diff < 0:
            advantage = -grade_diff
            add(
                "extreme",
                {"label": contradiction.get("loss_label"), "weight": contradiction.get("weight")},
                _rising_ratio(advantage, contradiction.get("start_gap"), contradiction.get("full_gap")),
                f"失败且我方团队总评分-敌方={round(advantage, 2)}",
                "详情JSON",
            )

    score_cap = _number(rules.get("score_cap", 100), 100)
    capped_scores = {
        category: min(score_cap, scores[category])
        for category in category_order
    }
    rounded_scores = {
        category_rules.get(category, {}).get("label", category): _display_number(capped_scores[category])
        for category in category_order
    }
    representative_key = max(category_order, key=lambda category: capped_scores[category])
    representative_label = category_rules.get(representative_key, {}).get("label", representative_key)
    selected_breakdown = breakdowns[representative_key]
    selected_tags = [f"【{item['factor']}】" for item in selected_breakdown]
    labeled_breakdowns = {
        category_rules.get(category, {}).get("label", category): breakdowns[category]
        for category in category_order
    }

    return {
        "score": _display_number(capped_scores[representative_key]),
        "representative_category": representative_label,
        "category_scores": rounded_scores,
        "tags": selected_tags,
        "breakdown": selected_breakdown,
        "category_breakdowns": labeled_breakdowns,
        "detail_metrics": detail_metrics,
        "has_detail": bool(context),
    }


def ranking_key(candidate):
    """Select the largest category score, then apply deterministic tie-breaks."""
    return (
        _number(candidate.get("RepScore")),
        len(candidate.get("ScoreBreakdown") or []),
        1 if candidate.get("HasDetail") else 0,
        abs(_number(candidate.get("Grade")) - 8),
        _number(candidate.get("Duration")),
        _number(candidate.get("GameTimeTimestamp")),
    )


def category_ranking_key(candidate, category_label):
    """Rank one candidate within a specific representative category."""
    category_scores = candidate.get("CategoryScores") or {}
    category_breakdowns = candidate.get("CategoryBreakdowns") or {}
    return (
        _number(category_scores.get(category_label)),
        len(category_breakdowns.get(category_label) or []),
        1 if candidate.get("HasDetail") else 0,
        abs(_number(candidate.get("Grade")) - 8),
        _number(candidate.get("Duration")),
        _number(candidate.get("GameTimeTimestamp")),
    )
