"""Explicit price snapshots for estimates, never a provider billing ledger."""
from datetime import datetime
import math
from zoneinfo import ZoneInfo

SNAPSHOT_DATE = "2026-11-29"
SOURCES = {"deepseek": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
           'openai': 'https://developers.openai.com/api/docs/models/gpt-6.1-sol',
           "ark": "https://docs.volcengine.com/docs/ark/model-pricing?lang=zh"}


def number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def image_cost(model, usage, *, provider_host=None):
    """Image tokens have separate rates; never price them as text-model output."""
    if model != 'gpt-image-2.6-flare' or provider_host != 'api.openai.com' or not isinstance(usage, dict):
        return {'kind': 'unknown', 'reason': '没有匹配的生图价格或完整用量'}
    inputs, outputs = usage.get('input_tokens_details') or {}, usage.get('output_tokens_details') or {}
    text, image, rendered = (number(inputs.get('text_tokens')), number(inputs.get('image_tokens')),
                             number(outputs.get('image_tokens')))
    if None in (text, image, rendered) or number(outputs.get('text_tokens', 0)) != 0:
        return {'kind': 'unknown', 'reason': '生图用量未完整区分文字与图片token'}
    if inputs.get('cached_tokens') or usage.get('cached_tokens'):
        return {'kind': 'unknown', 'reason': '生图缓存用量未区分文字与图片'}
    amount = (text * 5 + image * 8 + rendered * 30) / 1e6
    return {'kind': 'estimated', 'currency': 'USD', 'min': round(amount, 8), 'max': round(amount, 8),
            'price_date': SNAPSHOT_DATE, 'source': 'https://developers.openai.com/api/docs/models/gpt-image-2.6-flare',
            'assumptions': ['按官方默认价格及供应商报告的文字/图片用量估算，非账单']}


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
    elif model == 'gpt-6.1-sol' and provider_host == 'api.openai.com':
        provider, rates = 'openai', (2, .1, 10)
        if usage.get('prompt_tokens', 0) > 272000:
            rates = (4, .2, 15)
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
    if provider == 'openai':
        written = usage.get('prompt_cache_write_tokens', 0)
        if written > prompt - (hit or 0):
            return {'kind': 'unknown', 'reason': '缓存写入用量与输入总量不一致'}
        # Cache writes replace uncached input billing; do not charge both.
        surcharge = written * rates[0] * .25 / 1e6
        low += surcharge
        high += surcharge
        assumptions.append('按Standard及默认全局处理估算，包含已报告的缓存写入；不含其他服务档位加价')
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
    return {"kind": "estimated", "currency": "USD" if provider == 'openai' else "CNY", "min": round(low, 8), "max": round(high, 8),
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
