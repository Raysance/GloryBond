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

    # --- 原始聊天日志 (Raw Chat Logs for Summary) ---

    def log_raw_chat(self, qid: str, text: str):
        """保存用户的原始发言记录（不包含 AI 回复），用于每日总结"""
        key = self._get_key("raw_logs", qid)
        item = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "text": text
        }
        self.redis.rpush(key, json.dumps(item, ensure_ascii=False))
        # 保留最近 100 条原始发言，确保够总结
        self.redis.ltrim(key, -100, -1)

    def get_raw_logs(self, qid: str) -> List[str]:
        """获取用户当天的所有原始发言内容"""
        key = self._get_key("raw_logs", qid)
        records = self.redis.lrange(key, 0, -1)
        res = []
        for raw_item in records:
            item = json.loads(raw_item)
            res.append(f"[{item['time']}] {item['text']}")
        return res

    def clear_raw_logs(self, qid: str):
        """总结后清除原始记录"""
        key = self._get_key("raw_logs", qid)
        self.redis.delete(key)

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
        """从 Redis 加载用户的个体对话记录，包含相对时间展示"""
        from .ztime import time_r
        now = time_r()
        key = self._get_key("chats", qid)
        records = self.redis.lrange(key, -num_records, -1)
        
        def get_rel_time(time_str):
            try:
                dt = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                diff = now - dt
                if diff.total_seconds() < 60: return "刚刚"
                if diff.total_seconds() < 3600: return f"{int(diff.total_seconds() // 60)}分钟前"
                if diff.total_seconds() < 86400: return f"{int(diff.total_seconds() // 3600)}小时前"
                return f"{int(diff.total_seconds() // 86400)}天前"
            except: return time_str

        res = ""
        for i, raw_item in enumerate(records, 1):
            item = json.loads(raw_item)
            rel_time = get_rel_time(item['time'])
            res += f"记录 {i} ({rel_time}):\n问题: {item['Q']}\n回答: {item['A']}\n\n"
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

    # --- 全体对话 (聚合各用户最近对话) ---

    def load_global_memory(self, num_records: int = 10) -> str:
        """从所有用户的记录中各取最后一条，组合成全体背景"""
        from .zstatic import qid as qid_dict
        from .zfunc import qid2nick
        
        all_last_chats = []
        for nick_name, user_qid in qid_dict.items():
            key = self._get_key("chats", str(user_qid))
            last_record = self.redis.lrange(key, -1, -1)
            if last_record:
                item = json.loads(last_record[0])
                item['nick'] = qid2nick(str(user_qid))
                all_last_chats.append(item)
        
        # 按时间排序，取最近的 num_records 条
        all_last_chats.sort(key=lambda x: x['time'], reverse=True)
        recent_chats = all_last_chats[:num_records]
        recent_chats.reverse() # 正序展示

        res = ""
        for item in recent_chats:
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
        获取用户近期的历史战绩并转换为自然语言描述，包含相对时间和更多细节
        """
        from .zfunc import fetch_history
        from .ztime import time_r, str_to_time
        import datetime
        
        # 1. 查找 qid 对应的 userid
        target_userid = None
        target_realname = None
        
        from .zstatic import userlist, qid as qid_dict
        
        for realname, user_qid in qid_dict.items():
            if str(user_qid) == str(qid):
                target_realname = realname
                target_userid = userlist.get(realname)
                break
        
        if not target_userid:
            return "暂未找到该用户的角色关联信息。"

        # 2. 获取历史数据
        now = time_r()
        end_date = now
        start_date = end_date - datetime.timedelta(days=days)
        
        history_data, _ = fetch_history(userid=target_userid, start_date=start_date, end_date=end_date)
        
        details = history_data.get(target_realname, [])
        if not details:
            return f"该用户在最近 {days} 天内没有比赛记录。"

        def get_relative_time_str(target_time_str, date_str):
            """计算相对时间描述"""
            try:
                # 假设 date_str 是 "MM-DD" 格式，需要补全年份
                current_year = now.year
                target_dt = datetime.datetime.strptime(f"{current_year}-{date_str} {target_time_str}", "%Y-%m-%d %H:%M")
                # 如果计算出来的时间比现在还晚，可能是跨年的情况
                if target_dt > now:
                    target_dt = target_dt.replace(year=current_year - 1)
                
                diff = now - target_dt
                seconds = diff.total_seconds()
                
                if seconds < 3600:
                    return f"{int(seconds // 60)}分钟前"
                elif seconds < 86400:
                    return f"{int(seconds // 3600)}小时前"
                else:
                    return f"{int(seconds // 86400)}天前"
            except:
                return target_time_str

        # 3. 转换为自然语言输出
        summary = f"用户 {target_realname} 最近 {days} 天的历史表现概览（当前时间：{now.strftime('%H:%M')}）：\n"
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
            
            # 提取 Others 中的额外信息
            others = detail.get("Others", "").strip()
            extra_tags = []
            if "MVP" in others.upper(): extra_tags.append("MVP")
            if "超神" in others: extra_tags.append("超神")
            if "一血" in others: extra_tags.append("拿下一血")
            extra_info = f"【{' '.join(extra_tags)}】" if extra_tags else ""
            
            # 计算相对时间
            rel_time = get_relative_time_str(detail.get("GameTime", ""), detail.get("Date", now.strftime("%m-%d")))
            
            summary += f"- {rel_time} 在 {map_name} 使用 {hero} 获得{res}，战绩 {k}/{d}/{a}，评分 {grade} {extra_info}\n"
            
        return summary

    # --- 清除个体记忆 ---

    def clear_user_data(self, qid: str):
        """清除用户的所有 Redis 键"""
        self.redis.delete(self._get_key("chats", qid))
        self.redis.delete(self._get_key("notes", qid))

# 实例化单例
instance = ZMemory() 
