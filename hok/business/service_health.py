"""Cheap, explicit service-check inventory and QQ report formatting."""


def http_targets(config, chat, search, proxy, profiles):
    """Use the same resolved provider settings and proxy routes as production."""
    targets = []

    def add(name, url, *, route="", check="reachability", **options):
        targets.append(dict(name=name, category="外部服务", url=url, proxy=route,
                            check=check, **options))

    for name, provider in (("聊天模型", chat), ("备用聊天模型", chat.get("fallback", {}))):
        add(name, provider.get("base_url", "").rstrip("/") + "/models" if provider else "",
            route=provider.get("proxy_url", ""), check="models",
            api_key=provider.get("api_key", ""), model=provider.get("model", ""))
    qq = config.get("QQBot", {})
    add("Ark 文案模型", "https://ark.cn-beijing.volces.com/api/v3/models", check="models",
        api_key=qq.get("ark_key", ""))
    # Image permissions/generation cannot be inferred from the text-model key.
    add("Ark 图片服务", "https://ark.cn-beijing.volces.com/api/v3/", configured=bool(qq.get("ark_image_key")))
    add("APIMart 图片服务", "https://api.apimart.ai/v1/", route=proxy, requires_proxy=True,
        configured=bool(qq.get("apimart_key")))
    add("阿里云搜索", search.get("endpoint", ""), configured=bool(search.get("api_key")))
    add("王者营地", "https://kohcamp.qq.com/game/curseasonpage",
        configured=bool(config.get("wzry", {}).get("token")))
    add("王者英雄资源", "https://ssl.kohsocialapp.qq.com/play/h5getherolist")
    add("天元之弈", "https://tianyuanzhiyi.com/api/global/tier")
    add("B站 API", "https://api.bilibili.com/x/web-interface/nav", check="bilibili")
    add("B站网页", "https://www.bilibili.com/")
    add("B站图片", "https://i0.hdslb.com/")
    add("Steam", "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/",
        route=proxy, requires_proxy=True, check="steam", api_key=config.get("Steam", {}).get("api_key", ""))
    enabled_x = config.get("XSubscriptions", {}).get("enabled", True)
    for name, url in (("X 网页", "https://x.com/home"), ("X 脚本", "https://abs.twimg.com/"),
                      ("X 图片", "https://pbs.twimg.com/")):
        add(name, url, route=proxy, requires_proxy=True, enabled=enabled_x,
            configured=(bool(config.get("XSubscriptions", {}).get("auth_token")
                             and config.get("XSubscriptions", {}).get("ct0")) if name == "X 网页" else True))
    daily = config.get("AIDaily", {})
    add("AI 日报", daily.get("api_base_url", "").rstrip("/") + "/dailies/latest",
        enabled=daily.get("enabled", True))
    kpl = config.get("AgentKPL", {})
    add("KPL 数据", kpl.get("api_base_url", ""), enabled=kpl.get("enabled", True))
    add("QQ 头像", profiles.get("avatar_endpoint", "https://q1.qlogo.cn/g"))
    for name, url in (("Emoji CDN", "https://cdnjs.cloudflare.com/"),
                      ("Emoji 备用 CDN", "https://twemoji.maxcdn.com/"),
                      ("Emoji jsDelivr", "https://cdn.jsdelivr.net/")):
        add(name, url)
    for endpoint in config.get("ServiceHealth", {}).get("http_endpoints", []):
        targets.append(dict(name=endpoint["name"], category="服务器接口", url=endpoint["url"],
                            proxy="", check=endpoint.get("check", "http")))
    domain = config.get("WebService", {}).get("server_domain", "")
    if domain:
        targets.append(dict(name="HOK 公网入口", category="服务器接口",
                            url=f"https://hok.{domain}/health", proxy="", check="web_health"))
    return targets


def format_report(results, elapsed):
    """Return exactly two forward nodes; unverified checks need attention."""
    labels = {"ok": "正常", "reachable": "仅可达", "warn": "注意", "error": "异常", "skip": "跳过"}
    nodes = []
    for healthy, title in ((False, "有问题或待确认的服务"), (True, "没问题的服务")):
        items = [item for item in results if (item["status"] == "ok") == healthy]
        lines = [f"Bot 服务检查 · {title}（{len(items)}项）", f"本次检查耗时 {elapsed:.1f}秒"]
        if not healthy:
            lines.append("仅可达、跳过及未完成的检查也列在此处，不代表已确认故障。")
        for category in dict.fromkeys(item["category"] for item in items):
            lines.append(f"【{category}】")
            for item in items:
                if item["category"] != category:
                    continue
                duration = f" · {item['ms']}ms" if "ms" in item else ""
                lines.append(f"[{labels[item['status']]}] {item['name']}：{item['detail']}{duration}")
        if not items:
            lines.append("无。" if not healthy else "暂无已确认正常的服务。")
        nodes.append("\n".join(lines))
    return nodes
