"""Ask the requesting viewer, then deliver that exact battle through the usual UI."""
import asyncio
from types import SimpleNamespace

from glorybond.storage import watch_reports as store
from glorybond.config.settings import confs, userlist, roleidlist
from glorybond.time import current_timestamp


class ReportStopped(RuntimeError):
    """A locally constructed, safe explanation for stopping this request."""


def reply_scope(event):
    group = getattr(event, "group_id", None)
    actor = str(event.get_user_id())
    return [str(confs["QQBot"]["bot_qid"]), "group" if group else "private",
            str(group) if group else actor, actor]


def ask_after_watch(prepared, result, *, event):
    from glorybond.apps.qq.message_sender import add_msg, offer_watch_report

    reference = result.get("battle_reference")
    if reference is None:
        store.dismiss(reply_scope(event))
        add_msg("该局暂未返回完整的战绩标识，无法设置结束推送。", event=event)
        return False
    target = {key: prepared[key] for key in ("name", "userid", "roleid", "display_name")}
    return offer_watch_report(reply_scope(event), target, reference, event=event)


def has_pending(event):
    return store.pending(reply_scope(event)) is not None


async def answer_after_watch(event):
    from glorybond.apps.qq.message_sender import add_msg

    if event.get_plaintext().strip() not in {"是", "否"}:
        return
    scope = reply_scope(event)
    record = await asyncio.to_thread(store.pending, scope)
    if record is None:
        return
    accepted = event.get_plaintext().strip() == "是"
    result = await asyncio.to_thread(store.answer, scope, record, accepted, now=current_timestamp())
    if result == 1:
        name = record["target"]["display_name"]
        text = (f"已开启【{name}】本局结束战绩推送，战绩同步后发到这里。" if accepted
                else f"好的，不推送【{name}】这局的结束战绩。")
    elif result == -1:
        text = "当前等待推送的对局较多，暂时无法新增。"
    else:
        text = "这次确认已过期，请重新观战后设置。"
    add_msg(text, event=event)


def _report_failure(job, error):
    from glorybond.apps.qq.errors import report_exception

    event = SimpleNamespace(user_id=job["scope"][3], get_user_id=lambda: job["scope"][3])
    if job["scope"][1] == "group":
        event.group_id = job["scope"][2]
    report_exception(error, operation="观战结束战绩推送", event=event)


async def check_pending_reports():
    from glorybond.apps.qq.handlers.player_reports import single_last_battle_reply
    from glorybond.apps.qq.message_sender import add_watch_report_msg
    from glorybond.apps.qq.rules import is_battle_visible_qid_enabled
    from glorybond.features.game.watch_report import completed_battle_params
    from glorybond.features.facade import wzry_get_official

    jobs = await asyncio.to_thread(store.claim_due, str(confs["QQBot"]["bot_qid"]), now=current_timestamp())
    pages = {}
    for job in jobs:
        try:
            target = job["target"]
            allowed = await asyncio.to_thread(is_battle_visible_qid_enabled, job["scope"][3])
            if (str(userlist.get(target["name"])) != str(target["userid"])
                    or str(roleidlist.get(target["name"])) != str(target["roleid"])
                    or not allowed):
                raise ReportStopped("玩家绑定或查询权限已变化，本次结束推送已停止")
            if current_timestamp() >= job["deadline"]:
                raise ReportStopped("两小时内未取得该局战绩，本次结束推送已停止")
            key = str(target["userid"]), str(target["roleid"])
            if key not in pages:
                try:
                    pages[key] = await asyncio.to_thread(wzry_get_official, "btlist", priority="low",
                                                        userid=target["userid"], roleid=target["roleid"])
                except Exception as error:
                    pages[key] = error
            if isinstance(pages[key], Exception):
                raise ReportStopped("战绩查询失败（" + type(pages[key]).__name__ + "），本次结束推送已停止")
            params = job["reference"]["params"]
            try:
                completed_params = completed_battle_params(pages[key], params)
            except PermissionError:
                raise ReportStopped("该玩家战绩不可见，本次结束推送已停止") from None
            if completed_params is None:
                continue
            battle = await single_last_battle_reply({"battle_params": completed_params, "battle_roleid": target["roleid"]})
            if battle is None:
                # A history row may appear before the detail is available.
                continue
            if battle["text"].startswith("最后一局 "):
                battle = {**battle, "text": "观战对局战绩 " + battle["text"].removeprefix("最后一局 ")}
            await asyncio.to_thread(add_watch_report_msg, job, battle)
        except Exception as error:
            safe = error if isinstance(error, ReportStopped) else RuntimeError(
                "自动战绩推送失败（" + type(error).__name__ + "），本次已停止")
            if await asyncio.to_thread(store.finish, job):
                _report_failure(job, safe)
        finally:
            await asyncio.to_thread(store.release, job)
