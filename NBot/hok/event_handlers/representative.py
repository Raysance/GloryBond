"""Representative-battle command parsing and result normalization."""

import asyncio


async def representative_query_reply(raw_message):
    from ..zfunc import representative_battle_query_impl

    result = await asyncio.to_thread(
        representative_battle_query_impl,
        str(raw_message or "").strip(),
    )
    if not result["found"]:
        return {
            "kind": "text",
            "text": f"{result['target_date']} 暂无可用的代表局",
        }
    return {
        "kind": "battle",
        "text": result["text"],
        "image_path": result["image_path"],
        "commentary": result["commentary"],
    }


def _daily_debug_text(best_info):
    lines = [
        "",
        "[调试-筛选准则]",
        f"● 代表类型: {best_info.get('RepresentativeCategory')}",
        f"● 代表性指数: {best_info.get('RepScore')}/100",
    ]
    category_scores = best_info.get("CategoryScores", {})
    if category_scores:
        score_text = " / ".join(
            f"{name}{score}" for name, score in category_scores.items()
        )
        lines.append(f"● 三类指数: {score_text}")
    lines.append(f"● 依据标签: {' '.join(best_info.get('RawTags', [])) or '无'}")
    breakdown = best_info.get("ScoreBreakdown", [])
    if breakdown:
        lines.append("● 代表类型分项:")
        for item in breakdown:
            lines.append(
                f"  - {item.get('factor')} "
                f"{item.get('contribution')}/{item.get('max_weight')}"
                f"（{item.get('condition')}）"
            )
    summary = best_info.get("FilterSummary", {})
    if summary:
        lines.append(
            "● 筛选统计: "
            f"扫描{summary.get('scanned', 0)}局，"
            f"地图剔除{summary.get('official_map_rejected', 0)}局，"
            f"规则剔除{summary.get('rule_rejected', 0)}局，"
            f"合并重复视角{summary.get('duplicate_perspectives', 0)}个，"
            f"最终候选{summary.get('eligible_unique_battles', 0)}局"
        )
    lines.append(
        f"● 深度数据: {'已参与评分' if best_info.get('HasDetail') else '缺失，仅按摘要评分'}"
    )
    if best_info.get("DetailReason"):
        lines.append(f"● 深度原因: {best_info.get('DetailReason')}")
    return "\n".join(lines)


async def daily_representative_debug_reply(raw_message):
    from ..zfunc import get_daily_representative_battle

    target_date = str(raw_message or "").strip().replace("##srep", "").strip() or None
    result = await asyncio.to_thread(
        get_daily_representative_battle,
        target_date=target_date,
    )
    if not result:
        return {
            "kind": "text",
            "text": (
                f"未发现 {target_date or '今日'} 的对局数据，"
                "请确认 history 目录下 JSON 已生成"
            ),
        }
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return {"kind": "text", "text": f"数据格式异常: {result}"}
    text, image_path = result[:2]
    best_info = result[2] if len(result) >= 3 else {}
    return {
        "kind": "battle",
        "text": text + (_daily_debug_text(best_info) if best_info else ""),
        "image_path": image_path,
        "commentary": best_info.get("AiCommentary") if best_info else None,
        "acknowledgement": "代表局调试结果已私聊发送",
    }


async def representative_range_debug_replies(raw_message):
    from ..zfunc import representative_battle_range_debug_impl

    result = await asyncio.to_thread(
        representative_battle_range_debug_impl,
        str(raw_message or "").strip(),
    )
    return list(result["day_reports"])
