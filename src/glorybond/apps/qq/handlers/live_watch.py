"""Named live screenshot commands, using the same player directory as predictions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

from hok_camp_client import CampError
from glorybond.config.settings import namenick, roleidlist, userlist


def watch_target(text):
    text = text.strip()
    if not text.startswith(("#", "＃")):
        return None
    body = text[1:].strip()
    if body.startswith("观战"):
        return body[2:].strip()
    if body.endswith("的观战"):
        return body[:-3].strip()
    return None


def prepare_watch_request(event):
    from glorybond.features.facade import extract_name, qid2realname

    target = watch_target(event.get_plaintext())
    if not target:
        return {"kind": "text", "text": "请使用 #观战昵称 或 #观战我"}
    if target in {"我", "我的"}:
        name = qid2realname(event.get_user_id())
    else:
        name = target if target in userlist else extract_name(target, precise=True)
    if not name or name not in userlist or name not in roleidlist:
        return {"kind": "text", "text": "没有找到已登记的玩家，请使用配置中的昵称"}
    if str(userlist[name]) in {"", "0", "-1", "None"} or str(roleidlist[name]) in {"", "0", "-1", "None"}:
        return {"kind": "text", "text": "该玩家尚未配置完整的游戏账号"}
    display = namenick.get(name, name)
    return {"kind": "ready", "name": name, "userid": userlist[name], "roleid": roleidlist[name],
            "display_name": display, "status": f"正在获取【{display}】的观战截图，首次加载可能需要约一分钟…"}


def _capture(prepared, *, on_lineup=None, on_error=None):
    from glorybond.integrations.wzry import wzry_watch_frame
    from glorybond.storage.files import save_watch_frame

    display = prepared["display_name"]

    def show_lineup(battle_info):
        from glorybond.features.game.watch_lineup import prepare_watch_lineup
        try:
            lineup = prepare_watch_lineup(battle_info, role_id=prepared["roleid"])
            if lineup is not None:
                on_lineup(lineup)
        except Exception as error:
            # A missing/broken card must not restart or discard the live session.
            if on_error:
                on_error(RuntimeError("观战阵容图片生成或入队失败（" + type(error).__name__ + "）"))

    # The SDK calls back before consuming live-ready notifications. Downloads and
    # rendering must run separately so they cannot exhaust that wait or delay its
    # heartbeat. Join before returning to preserve lineup-before-screenshot order.
    lineup_worker = (ThreadPoolExecutor(max_workers=1, thread_name_prefix="watch-lineup")
                     if on_lineup is not None else None)
    try:
        options = ({"on_battle_info": lambda info: lineup_worker.submit(show_lineup, info)}
                   if lineup_worker is not None else {})
        result = wzry_watch_frame(prepared["userid"], prepared["roleid"], **options)
        if result["state"] == "ready":
            from glorybond.features.game.watch_report import battle_reference
            return {"kind": "image", "text": f"【{display}】观战画面",
                    "image_path": save_watch_frame(result["jpeg"]),
                    "battle_reference": battle_reference(result.get("battle_info"), role_id=prepared["roleid"])}
        text = {"pending": "等待营地直播就绪通知超时，请稍后再次观战", "ended": "该对局已结束"}.get(
            result["state"], "当前对局暂时无法观战")
        return {"kind": "text", "text": text}
    except CampError as error:
        if error.code == "watch_unavailable":
            reason = error.response.get("reason") if isinstance(error.response, dict) else None
            text = f"【{display}】当前不在对局中" if reason == "not_gaming" else f"【{display}】当前对局暂时无法观战"
        else:
            text = {"watch_active": "正在获取另一张观战截图，请稍后再试",
                    "logged_out": "营地尚未登录，请联系管理员",
                    "im_credentials": "营地登录信息不完整，请管理员在账号页面处理",
                    "im_login": "营地观战登录未成功，本次已停止",
                    "session_changed": "营地登录态刚刚更新，本次已停止",
                    "video_decode": "暂时无法读取观战画面，本次已停止",
                    "video_dependency": "观战组件尚未安装，请联系管理员"}.get(error.code,
                        "暂时无法获取观战截图，本次已停止")
        if on_error and error.code not in {"watch_unavailable", "watch_active"}:
            on_error(RuntimeError(text + f"（{error.code}）"))
            return {"kind": "reported", "text": text}
        return {"kind": "text", "text": text}
    except Exception as error:
        if on_error:
            on_error(RuntimeError("暂时无法获取观战截图，本次已停止（" + type(error).__name__ + "）"))
            return {"kind": "reported", "text": "暂时无法获取观战截图，本次已停止"}
        return {"kind": "text", "text": "暂时无法获取观战截图，本次已停止"}
    finally:
        if lineup_worker is not None:
            lineup_worker.shutdown(wait=True)


def send_watch_lineup(lineup, *, event):
    from glorybond.apps.qq.message_sender import add_watch_lineup_msg, watch_lineup_queued
    from glorybond.features.game.watch_lineup import render_watch_lineup_file

    if watch_lineup_queued(lineup["battle_id"], event=event):
        return False
    return add_watch_lineup_msg(lineup["battle_id"], render_watch_lineup_file(lineup), event=event)


async def run_watch_request(prepared, *, on_lineup=None, on_error=None):
    return await asyncio.to_thread(_capture, prepared, on_lineup=on_lineup, on_error=on_error)
