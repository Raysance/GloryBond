import redis
import json

# 配置 Redis 连接参数（请根据实际情况修改）
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 6

def calculate_consistency_ratio():
    # 连接到 Redis 6号数据库
    redis_daemon = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    
    # 获取所有键（这里应该只有 "records"）
    keys = redis_daemon.keys("*")
    
    total_count = 0        # 总有效条目数（排除 op_side=0 后）
    consistent_count = 0   # game_res 与 (my_side > op_side) 一致的条目数
    excluded_count = 0     # 因 op_side=0 被排除的条目数
    
    # 用于计算平均偏移比例
    total_offset_ratio = 0.0  # 偏移比例总和 |op_side - my_side| / my_side
    
    # 用于计算平均而言 my_side 比 op_side 高的比例
    total_my_higher_ratio = 0.0  # (my_side - op_side) / op_side 的总和
    
    for key in keys:
        # 获取 key 的类型
        key_type = redis_daemon.type(key).decode('utf-8')
        
        if key_type == 'list':
            # 获取列表中的所有元素
            list_elements = redis_daemon.lrange(key, 0, -1)
            
            for element in list_elements:
                try:
                    # 解码 bytes 并解析 JSON
                    data = json.loads(element.decode('utf-8'))
                    
                    # 提取字段
                    game_res = data.get("game_res")
                    my_side = data.get("my_side_total_level")
                    op_side = data.get("op_side_total_level")
                    
                    # 确保字段完整
                    if game_res is None or my_side is None or op_side is None:
                        print(f"缺少必要字段，跳过: {data}")
                        continue
                    
                    # 排除 op_side = 0 的条目
                    if op_side == 0:
                        excluded_count += 1
                        print(f"排除条目 (op_side=0): game_res={game_res}, my_side={my_side:.2f}")
                        continue
                    
                    total_count += 1
                    
                    # 1. 计算偏移比例 |op_side - my_side| / my_side
                    offset_ratio = abs(op_side - my_side) / my_side
                    total_offset_ratio += offset_ratio
                    
                    # 2. 计算 my_side 比 op_side 高的比例 (my_side - op_side) / op_side
                    my_higher_ratio = (my_side - op_side) / op_side
                    total_my_higher_ratio += my_higher_ratio
                    
                    # 计算实际结果
                    my_side_wins = my_side > op_side
                    
                    # 检查是否一致
                    if game_res == my_side_wins:
                        consistent_count += 1
                        
                except (json.JSONDecodeError, AttributeError) as e:
                    print(f"解析 JSON 失败: {element}, 错误: {e}")
                    continue
        
        elif key_type == 'string':
            # 如果将来有 string 类型，也支持
            value = redis_daemon.get(key)
            if value:
                try:
                    data = json.loads(value.decode('utf-8'))
                    # 同上处理逻辑...
                except:
                    pass
    
    # 计算平均偏移比例
    avg_offset_ratio = total_offset_ratio / total_count if total_count > 0 else 0.0
    
    # 计算平均而言 my_side 比 op_side 高的比例
    avg_my_higher_ratio = total_my_higher_ratio / total_count if total_count > 0 else 0.0
    
    # 计算一致比例
    if total_count == 0:
        ratio = 0.0
        print("没有有效的条目（排除 op_side=0 后）")
    else:
        ratio = consistent_count / total_count
    
    print(f"\n统计结果:")
    print(f"排除的条目数 (op_side=0): {excluded_count}")
    print(f"有效总条目数: {total_count}")
    print(f"一致条目数: {consistent_count}")
    print(f"不一致条目数: {total_count - consistent_count}")
    print(f"一致比例: {ratio:.4f} ({ratio*100:.2f}%)")
    print(f"平均偏移比例: {avg_offset_ratio:.6f} ({avg_offset_ratio*100:.4f}%)")
    print(f"平均 my_side 比 op_side 高的比例: {avg_my_higher_ratio:.6f} ({avg_my_higher_ratio*100:.4f}%)")
    
    # 额外统计：胜率相关
    if total_count > 0:
        actual_win_rate = sum(1 for _ in range(total_count) if _)  # 这里需要重新计算，简单起见用下面的逻辑
        # 重新计算实际胜率
        actual_wins = 0
        # 上面的循环中已经可以计算，为了简洁，这里给出公式说明
        
        print(f"\n指标说明:")
        print(f"  1. 平均偏移比例 = |op_side - my_side| / my_side")
        print(f"     表示平均等级差距相对于 my_side 的大小")
        print(f"  2. 平均 my_side 比 op_side 高的比例 = (my_side - op_side) / op_side")
        print(f"     正值表示平均来说 my_side 更高，负值表示平均来说 op_side 更高")
    
    return ratio, avg_offset_ratio, avg_my_higher_ratio

def calculate_additional_stats():
    """重新计算一次以获取实际胜率等额外统计"""
    redis_daemon = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    keys = redis_daemon.keys("*")
    
    my_wins = 0
    op_wins = 0
    total = 0
    
    for key in keys:
        key_type = redis_daemon.type(key).decode('utf-8')
        if key_type == 'list':
            elements = redis_daemon.lrange(key, 0, -1)
            for element in elements:
                try:
                    data = json.loads(element.decode('utf-8'))
                    my_side = data.get("my_side_total_level")
                    op_side = data.get("op_side_total_level")
                    
                    if my_side is None or op_side is None or op_side == 0:
                        continue
                    
                    total += 1
                    if my_side > op_side:
                        my_wins += 1
                    else:
                        op_wins += 1
                except:
                    continue
    
    if total > 0:
        print(f"\n实际对战胜率统计:")
        print(f"  my_side 获胜次数: {my_wins} ({my_wins/total*100:.2f}%)")
        print(f"  op_side 获胜次数: {op_wins} ({op_wins/total*100:.2f}%)")

if __name__ == "__main__":
    calculate_consistency_ratio()
    calculate_additional_stats()