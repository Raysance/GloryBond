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

    # --- 个体短暂聊天记忆 (Individual Chat History) (May Expire) ---

    def save_chat(self, qid: str, question: str, answer: str):
        """保存用户的个体对话记录到 Redis List"""
        key = self._get_key("chats", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Q": question,
            "A": answer
        }
        # 将新记录推入列表右侧
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        # 保持最近 20 条
        self.redis.ltrim(key, -20, -1)

    def load_chat(self, qid: str, num_records: int = 3) -> str:
        """从 Redis 加载用户的个体对话记录"""
        key = self._get_key("chats", qid)
        # 获取最后 num_records 条
        records = self.redis.lrange(key, -num_records, -1)
        
        res = ""
        for i, raw_item in enumerate(records, 1):
            item = json.loads(raw_item)
            res += f"记录 {i}:\n时间: {item['time']}\n问题: {item['Q']}\n回答: {item['A']}\n\n"
        return res

    # --- 个体长效记忆 (Individual Long-term Memory/User Notes) (No Expire) ---

    def save_user_memory(self, qid: str, content: str):
        """保存用户的特定强调内容到 Redis List"""
        key = self._get_key("notes", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mem": content
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        # 限制存储数量
        self.redis.ltrim(key, -50, -1)

    def load_user_memory(self, qid: str, num_records: int = 10) -> str:
        """加载特定用户的强调记录"""
        key = self._get_key("notes", qid)
        records = self.redis.lrange(key, -num_records, -1)
        
        res = ""
        for i, raw_item in enumerate(records, 1):
            item = json.loads(raw_item)
            res += f"强调 {i} (时间: {item['time']}): {item['mem']}\n"
        return res

    # --- 全体对话 ---

    def add_global_memory(self, user_nick: str, question: str, answer: str):
        """保存全体对话的一条记录到 Redis List"""
        key = f"{self.prefix}global_chat"
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nick": user_nick,
            "Q": question,
            "A": answer
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        # 全体记忆保留最近 30 条对话
        self.redis.ltrim(key, -30, -1)

    def load_global_memory(self, num_records: int = 10) -> str:
        """加载全体对话记录"""
        key = f"{self.prefix}global_chat"
        records = self.redis.lrange(key, -num_records, -1)
        res = ""
        for raw_item in records:
            item = json.loads(raw_item)
            res += f"[{item['time']}] {item['nick']}: {item['Q']} -> {item['A']}\n"
        return res

    # --- 获取全体记忆 ---

    def get_all_users_memory(self, exclude_qid: Optional[str] = None, amnesia: bool = False, super_id: str = "") -> str:
        """
        扫描 Redis 中所有用户的强调记录
        """
        res = ""
        # 使用 scan 查找所有 notes 键
        pattern = self._get_key("notes", "*")
        
        for key in self.redis.scan_iter(match=pattern):
            # 解码并提取 qid
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            qid = key_str.split(":")[-1]
            
            if exclude_qid and qid == exclude_qid:
                continue
            
            if amnesia and str(super_id) not in qid:
                continue
            
            # 每个用户取最新几条
            records = self.redis.lrange(key, -5, -1)
            if records:
                res += f"用户 {qid} 的强调内容:\n"
                for raw_item in records:
                    item = json.loads(raw_item)
                    res += f"- {item['mem']} ({item['time']})\n"
        return res

    # --- 转换游戏历史数据为自然语言  ---

    def load_user_history_natural(self, qid: str, days: int = 7) -> str:
        """
        获取用户近期的历史战绩并转换为自然语言描述
        """
        from .zfunc import fetch_history
        from .ztime import time_r
        import datetime
        
        # 1. 查找 qid 对应的 userid
        target_userid = None
        target_realname = None
        
        # 从 zdynamic/zstatic 获取映射数据
        from .zstatic import userlist, qid as qid_dict
        
        for realname, user_qid in qid_dict.items():
            if str(user_qid) == str(qid):
                target_realname = realname
                target_userid = userlist.get(realname)
                break
        
        if not target_userid:
            return "暂未找到该用户的角色关联信息。"

        # 2. 获取历史数据 (fetch_history 返回 gamedetails, duration)
        end_date = time_r()
        start_date = end_date - datetime.timedelta(days=days)
        
        history_data, _ = fetch_history(userid=target_userid, start_date=start_date, end_date=end_date)
        
        details = history_data.get(target_realname, [])
        if not details:
            return f"该用户在最近 {days} 天内没有比赛记录。"

        # 3. 转换为自然语言输出
        summary = f"用户 {target_realname} 最近 {days} 天的历史表现概览：\n"
        # 只取最近 5 场细节
        recent_details = details[-5:]
        for detail in recent_details:
            res = detail.get("Result", "对局")
            hero = detail.get("HeroName", "英雄")
            map_name = detail.get("MapName", "未知地图")
            k = detail.get("KillCnt", 0)
            d = detail.get("DeadCnt", 0)
            a = detail.get("AssistCnt", 0)
            grade = detail.get("GameGrade", 0)
            time_str = detail.get("GameTime", "未知时间")
            summary += f"- {time_str} {map_name} 使用 {hero} 获得{res}，战绩 {k}/{d}/{a}，评分 {grade}\n"
            
        return summary

    # --- 清除个体记忆 ---

    def clear_user_data(self, qid: str):
        """清除用户的所有 Redis 键"""
        self.redis.delete(self._get_key("chats", qid))
        self.redis.delete(self._get_key("notes", qid))

# 实例化单例
instance = ZMemory() 
