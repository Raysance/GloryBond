"""Explicit price snapshots for estimates, never a provider billing ledger."""
from datetime import datetime
import math
from zoneinfo import ZoneInfo

SNAPSHOT_DATE = "2026-11-29"
SOURCES = {"deepseek": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
           "ark": "https://docs.volcengine.com/docs/ark/model-pricing?lang=zh"}


def number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def model_cost(model, usage, *, provider_host=None, at=None, raw_usage=None):
    raw = raw_usage if isinstance(raw_usage, dict) else {}
    reported = number(raw.get("cost"))
    currency = raw.get("cost_currency", raw.get("currency"))
    if reported is not None and currency in {"CNY", "USD"}:
        return {"kind": "reported", "currency": currency, "amount": reported}
    provider, rates = None, None
    if model in {"deepseek-flash", "deepseek-v4-pro"} and provider_host in {None, "api.deepseek.com"}:
        provider = "deepseek"
        rates = (1, .02, 4) if model == "deepseek-flash" else (4.5, .15, 13.5)
    elif isinstance(model, str) and model.startswith(("doubao-seed-2-1-pro-", "doubao-seed-2-1-lite-")) and provider_host in {None, "ark.cn-beijing.volces.com"}:
        provider = "ark"
        rates = (6, 1.2, 30) if "-pro-" in model else (.8, .16, 2.7)
    if not rates or not {"prompt_tokens", "completion_tokens"} <= usage.keys():
        return {"kind": "unknown", "reason": "没有匹配的官方价格或完整输入/输出用量"}
    prompt, output = usage["prompt_tokens"], usage["completion_tokens"]
    hit = usage.get("prompt_cache_hit_tokens")
    if hit is None and "prompt_cache_miss_tokens" in usage:
        hit = prompt - usage["prompt_cache_miss_tokens"]
    if hit is not None and not 0 <= hit <= prompt:
        return {"kind": "unknown", "reason": "缓存用量与输入总量不一致"}
    low_hit, high_hit = (hit, hit) if hit is not None else (prompt, 0)
    low = ((prompt - low_hit) * rates[0] + low_hit * rates[1] + output * rates[2]) / 1e6
    high = ((prompt - high_hit) * rates[0] + high_hit * rates[1] + output * rates[2]) / 1e6
    assumptions = ["按价格快照估算，非历史账单；不含账户优惠、赠金或税费"]
    if provider_host is None:
        assumptions.append("旧记录未保存端点，暂按模型名称对应的官方服务估算")
    if hit is None:
        assumptions.append("缓存命中用量缺失，返回全部命中到全部未命中的范围")
    if provider == "deepseek":
        try:
            stamp = datetime.fromisoformat(at)
            if stamp.tzinfo is None:
                raise ValueError("missing timezone")
            stamp = stamp.astimezone(ZoneInfo("Asia/Shanghai"))
            possible_peak = stamp.weekday() < 5 and (9 <= stamp.hour < 12 or 14 <= stamp.hour < 18)
        except (ValueError, TypeError):
            possible_peak = True
        if possible_peak:
            high *= 2
            assumptions.append("可能处于工作日高峰，未核验法定节假日，范围包含峰谷价格")
    return {"kind": "estimated", "currency": "CNY", "min": round(low, 8), "max": round(high, 8),
            "price_date": SNAPSHOT_DATE, "source": SOURCES[provider], "assumptions": assumptions}


def total_cost(items):
    totals, unknown = {}, 0
    for item in items:
        if item.get("kind") == "unknown":
            unknown += 1
            continue
        currency = item["currency"]
        row = totals.setdefault(currency, {"reported": 0, "estimated_min": 0, "estimated_max": 0})
        if item["kind"] == "reported":
            row["reported"] += item["amount"]
        else:
            row["estimated_min"] += item["min"]
            row["estimated_max"] += item["max"]
    return {"currencies": {currency: {key: round(value, 8) for key, value in row.items()}
                           for currency, row in totals.items()}, "unpriced_items": unknown,
            "coverage": "partial" if unknown else "recorded_calls",
            "notice": "只计已记录用量；失败、取消或未报告的供应商消耗可能缺失。估算不等于实际扣费；不同币种不相加。"}
