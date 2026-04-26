import os
import json
import datetime
from typing import List, Dict, Optional
from . import zdynamic as dmc

class ZMemory:
    def __init__(self):
        self.redis = dmc.redis_deamon_chat_memory
        self.prefix = "zmem:"

    def _get_key(self, category: str, qid: str) -> str:
        return f"{self.prefix}{category}:{qid}"

    # --- 1. 主动聊天记忆 (Active Chat) ---
    def save_active_chat(self, qid: str, question: str, answer: str):
        """保存用户与机器人对话记录 (f_chat中计入)"""
        key = self._get_key("active_chat", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Q": question,
            "A": answer
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        self.redis.ltrim(key, -10, -1) # 保留最近10条

    def load_active_chat(self, qid: str, num: int = 5) -> str:
        """加载当前用户的前 num 条主动聊天记忆"""
        key = self._get_key("active_chat", qid)
        records = self.redis.lrange(key, -num, -1)
        res = ""
        for i, raw_item in enumerate(records, 1):
            item = json.loads(raw_item)
            res += f"对话{i} ({item['time']}):\n问: {item['Q']}\n答: {item['A']}\n\n"
        return res

    # --- 2. 被动聊天记忆 (Passive Chat) ---
    def log_passive_chat(self, qid: str, text: str):
        """记录用户在群内的所有发言 (_all_messages 钩子)"""
        key = self._get_key("passive_chat", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "text": text
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        self.redis.ltrim(key, -100, -1) # 保留用于总结的日志

    def get_passive_logs(self, qid: str) -> List[str]:
        """获取用户原始发言日志用于总结"""
        key = self._get_key("passive_chat", qid)
        records = self.redis.lrange(key, 0, -1)
        return [f"[{json.loads(r)['time']}] {json.loads(r)['text']}" for r in records]

    def clear_passive_logs(self, qid: str):
        """总结后清理"""
        self.redis.delete(self._get_key("passive_chat", qid))

    def load_global_passive_memory(self, num_per_user: int = 1) -> str:
        """加载所有用户各自最新 num_per_user 条被动聊天记忆"""
        from .zstatic import qid as qid_dict
        from .zfunc import qid2nick
        res = ""
        for _, user_qid in qid_dict.items():
            user_qid = str(user_qid)
            key = self._get_key("passive_chat", user_qid)
            records = self.redis.lrange(key, -num_per_user, -1)
            if records:
                nick = qid2nick(user_qid)
                for r in records:
                    item = json.loads(r)
                    res += f"[{item['time']}] {nick}: {item['text']}\n"
        return res

    # --- 3. 主动强制记忆 (Forced Memory) ---
    def save_forced_memory(self, qid: str, content: str):
        """保存用户让机器人记住的内容"""
        key = self._get_key("forced_mem", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mem": content
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        self.redis.ltrim(key, -10, -1)

    def load_all_forced_memory(self, num_per_user: int = 5) -> str:
        """加载所有用户的前 num 条强制记忆"""
        from .zstatic import qid as qid_dict
        from .zfunc import qid2nick
        res = ""
        for _, user_qid in qid_dict.items():
            user_qid = str(user_qid)
            key = self._get_key("forced_mem", user_qid)
            records = self.redis.lrange(key, -num_per_user, -1)
            if records:
                nick = qid2nick(user_qid)
                res += f"【{nick}】的特别提醒:\n"
                for r in records:
                    item = json.loads(r)
                    res += f"- {item['mem']} ({item['time']})\n"
                res += "\n"
        return res

    # --- 4. 历史聊天提炼记忆 (Summary Memory) ---
    def save_summary_memory(self, qid: str, content: str):
        """保存由 daily_user_summary 提炼出的记忆"""
        key = self._get_key("summary_mem", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": content
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        self.redis.ltrim(key, -10, -1)

    def load_user_summary_memory(self, qid: str, num: int = 3) -> str:
        """加载当前用户的前 num 条总结记忆"""
        key = self._get_key("summary_mem", qid)
        records = self.redis.lrange(key, -num, -1)
        res = ""
        for i, r in enumerate(records, 1):
            item = json.loads(r)
            res += f"提炼{i} ({item['time']}): {item['summary']}\n"
        return res

    # --- 辅助与历史兼容 ---
    def load_user_history_natural(self, qid: str, days: int = 7) -> str:
        from .zfunc import fetch_history
        from .ztime import time_r
        import datetime
        target_userid = target_realname = None
        from .zstatic import userlist, qid as qid_dict
        for realname, user_qid in qid_dict.items():
            if str(user_qid) == str(qid):
                target_realname, target_userid = realname, userlist.get(realname)
                break
        if not target_userid: return "暂未找到该用户的角色关联信息。"
        now = time_r()
        history_data, _ = fetch_history(userid=target_userid, start_date=now - datetime.timedelta(days=days), end_date=now)
        details = history_data.get(target_realname, [])
        if not details: return f"该用户在最近 {days} 天内没有比赛记录。"
        summary = f"用户 {target_realname} 最近 {days} 天表现:\n"
        for detail in details[-5:]:
            summary += f"- {detail.get('Date')} {detail.get('HeroName')} {detail.get('Result')} KDA:{detail.get('KillCnt')}/{detail.get('DeadCnt')}/{detail.get('AssistCnt')}\n"
        return summary

    def clear_user_data(self, qid: str):
        for cat in ["active_chat", "passive_chat", "forced_mem", "summary_mem"]:
            self.redis.delete(self._get_key(cat, qid))

instance = ZMemory()
 
