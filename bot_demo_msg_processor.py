import datetime
import random
import re

# Simple state to simulate "context" for Poke
last_cmds = {} # userId -> last_cmd

async def process_message(message: str, user_id: str = "demo_user"):
    """
    Simulates HOK_QQBOT message processing.
    Covering all features with EXACT text from readme.md and real images.
    """
    message = message.strip()
    
    # Poke (戳一戳)
    if message == "戳一戳":
        last_cmd = last_cmds.get(user_id)
        if last_cmd == "战绩":
            return [
                {
                    "type": "text",
                    "content": "实力天平倾斜度：4.6\n我方底蕴：47.97\n我方英雄梯度：62.96\n对方底蕴：43.38\n对方英雄梯度：50.22"
                },
                {
                    "type": "image",
                    "content": "/bot_demo_assets/real_power.png"
                }
            ]
        else:
            return {
                "type": "text",
                "content": random.choice(["别戳了，再戳就坏了 (⊙x⊙;)", "哎呀，好痒呀~", "戳我干嘛，是不是想看我表演上分？"])
            }

    if not message.startswith("#"):
        return {
            "type": "text",
            "content": "请发送以 # 开头的指令，或尝试戳一戳机器人。所有指令在下方菜单可查。"
        }

    cmd_full = message[1:].strip()
    
    # 1. Ranking (#排行/#排名)
    if any(k in cmd_full for k in ["排行", "排名"]):
        last_cmds[user_id] = "排行"
        return {
            "type": "text",
            "content": """示例玩家65 下午好
2025-11-19 17:35

近5天最高最低评分：
      ↑示例玩家72的盾山：15.2分
      ↓示例玩家65的韩信：2.5分
机制受益受害者 ：
      示例玩家37：19.426
      示例玩家65：67.24

--- 上分榜 ---
今日上分最佳👆：LYG.KK
今日掉分最多👇：青训·奶龙@
    1.	LYG.KK	       +4
    2.	LYG.示例玩家33	       +3
    3.	芋圆糯塔塔铠	       +3
    4.	LYG.蒿芸	       +3
    5.	染尘烟夕	       +1
    6.	示例玩家70	       +1
    7.	LYG.未央	       +0
    8.	example_user_12	       +0
    9.	··舞··	       +0
    10.	青训·奶龙@	       -1

--- 场次榜 ---
今日场次最多👆：青训·奶龙@
    1.	青训·奶龙@	       19
    2.	芋圆糯塔塔铠	       9
    3.	LYG.蒿芸	       9
    4.	LYG.未央	       5
    5.	示例玩家70	       5
    6.	LYG.示例玩家33	       5
    7.	··舞··	       4
    8.	染尘烟夕	       3
    9.	LYG.KK	       3
    10.	example_user_12	       3

https://example_user_29.top/btlist?key=d9e1a47b041ea55c

今日峡谷风云变幻，数据之弦拨动命运的交响。示例玩家69的盾山如巍峨壁垒斩获巅峰评分，而示例玩家65的韩信却深陷低谷；示例玩家37与示例玩家65在机制浪潮中浮沉，一个受益登顶，一个负重前行。上分榜上LYG.KK以锐不可当之势领跑，青训·奶龙@则鏖战十九场独饮失意之酒。胜负皆成星火，照亮这片永恒征战的数字疆场。"""
        }

    # 2. Battle Record (#我的战绩)
    if "战绩" in cmd_full:
        last_cmds[user_id] = "战绩"
        return [
            {
                "type": "text",
                "content": """👀示例玩家65正在梦境大乱斗中玩貂蝉，0分钟前开局，快去看看。

🚩LYG.未央(11-15)的战报:
        场次：30
              -娱乐WIN：3 
              -匹配WIN：14 
              -排位WIN：0 
        平均评分: 8.383
      当前段位: 至尊星耀III 0⭐
      相比前一天 +⭐: 0
https://example_user_29.top/btlperson?key=ee99e01850b215c3

LYG.未央今天真是肝帝附体，狂打30场！排位赛海诺3-6战绩直接喜提败方MVP🤣，好在虞姬9-3怒抢MVP挽回颜面。凌晨还在梦境大乱斗用吕布砍下一血，这昼夜颠倒的征战，星耀段位怕是要被您熬成黑眼圈了😎"""
            },
            {
                "type": "text",
                "content": """最后一局 🏳️ 贡献: 1.14
排位赛 海诺: 3/6/3 6.9
https://example_user_29.top/btldetail?key=b49ab941926af0e9

戳一戳 来评估两方实力"""
            },
            {
                "type": "image",
                "content": "/bot_demo_assets/battle_detail.png"
            }
        ]

    # 3. Online status (#在线)
    if cmd_full == "在线":
        return {
            "type": "text",
            "content": """在线 2 人
─────────────
🎮 排位赛  15min
   • 示例玩家70 星耀IV  狄仁杰
   • example_user_12 星耀IV  小乔

Steam 在线 4 人
─────────────
💤 example_user_29  在线
🎮 柒悟  雀魂麻将(MahjongSoul)
🎮 Pheonix  Slay the Spire 2
💤 OneChan  在线"""
        }

    # 4. Query (#查询)
    if "查询" in cmd_full:
        return {
            "type": "text",
            "content": """🔍查询条件：玩家: 示例玩家71 | 评分比较: 示例玩家71 高于 示例玩家65 | 同局: 示例玩家65 | 地图: 排位赛

📊 统计概览 (15场)：
胜率: 53.3% (8胜7负)
平均评分: 9.3
场均KDA: 6.3/3.1/7.5 (4.50)

找到 15 局符合条件的战绩，点击链接查看详情：(视角随机)
https://example_user_29.top/btlquery?key=8540f36787523449"""
        }

    # 5. Hero Power (#我的战力)
    if "战力" in cmd_full:
        return {
            "type": "text",
            "content": """示例玩家59的战力英雄
元流之子(射手):   6418
   玉树州  No.33 
海诺:   6000
   玉树州  No.13 
沈梦溪:   4742
   玉树州  No.43 
周瑜:   4737
   玉树州  No.16 
甄姬:   4072
   称多县  No.20"""
        }

    # 6. Single player single hero (#🐷的蚩奼)
    if "蚩奼" in cmd_full:
        return {
            "type": "text",
            "content": """【统计信息】 🐷的蚩奼
━━━━━━━━━━━
战力  1913  (+1225)
总战绩  11胜10负  胜率52.4%
━━━━━━━━━━━
近30日表现
13场  胜率61.5%  均分9.9
MVP×4  牌子×4  KDA 6.5/3.0/4.4"""
        }

    # 7. Single player all heroes (#示例玩家41的英雄)
    if "英雄" in cmd_full and "群u" not in cmd_full:
        return {
            "type": "text",
            "content": """【统计信息】
示例玩家41的英雄汇总 
（近 30 天，共 93 场）
━━━━━━━━━━━
出场率 TOP:
  【甄姬】: 出场 20 场 (21.5%)
  胜率 55.0%  均分 8.2
  KDA 2.2/1.75/8.25
  【女娲】: 出场 11 场 (11.8%)
  胜率 54.5%  均分 7.7
  KDA 2.18/1.73/9.0
━━━━━━━━━━━
胜率 TOP (至少 2 场)：
  【东皇太一】: 胜率 100.0% (2 场)
  均分 9.0
  【哪吒】: 胜率 100.0% (3 场)
  均分 8.2
━━━━━━━━━━━
评分 TOP：
  【海诺】: 均分 9.8 (9 场)
  胜率 55.6%"""
        }

    # 8. All players single hero (#群u的哪吒)
    if "群u的" in cmd_full and "英雄" not in cmd_full:
        return {
            "type": "text",
            "content": """【统计信息】 群u的哪吒
（近 30 天）
━━━━━━━━━━━
总场次：127    参战玩家数：12
总胜率：63.0%    均分：8.66
 K/D/A：5.46/3.46/7.94
━━━━━━━━━━━
出场最多的玩家（Top 5）：
  【奶龙】: 40 场  胜率 62.5%  均分 9.08  KDA 5.42/2.65/7.03
  【示例玩家38】: 27 场  胜率 66.7%  均分 8.96  KDA 6.37/3.74/9.15"""
        }

    # 9. All players all heroes (#群u的英雄)
    if "群u的英雄" in cmd_full:
        return {
            "type": "text",
            "content": """【统计信息】
群u的英雄汇总
（近 30 天，共 1752 场）
━━━━━━━━━━━
出场率 TOP:
  哪吒: 出场 124 场 (7.1%)  胜率 62.1%  均分 8.6
  张飞: 出场 108 场 (6.2%)  胜率 61.1%  均分 8.1
  女娲: 出场 81 场 (4.6%)  胜率 55.6%  均分 9.0"""
        }

    # 10. Today's Hero (#今日英雄)
    if cmd_full == "今日英雄":
        return [
            {
                "type": "text",
                "content": "示例玩家59的今日英雄：妲己"
            },
            {
                "type": "image",
                "content": "/bot_demo_assets/today_hero.jpeg"
            },
            {
                "type": "text",
                "content": "示例玩家59，你的妲己战力飙升664！一技能冲击波消耗，二技能爱心晕眩1.5秒，接大招狐火连发。被动减敌人法防，让她秒人如传奇魅惑君王。56%胜率冲上荣耀！"
            }
        ]

    # 11. Analysis (#我的分析)
    if "分析" in cmd_full:
        return {
            "type": "image",
            "content": "/bot_demo_assets/grade_analyze.png",
            "text": "这是基于你最近100场对局生成的评分趋势分析图。"
        }
    
    # 14. Prediction (#示例玩家65的预言)
    if "预言" in cmd_full:
        return [
            {
                "type": "text",
                "content": "对局预言：186112_2197832512_1774537581\nLYG.未央  排位赛  沈梦溪\n\n实力天平倾斜度：-2.08\n我方底蕴：14.51\n我方英雄梯度：61.92\n对方底蕴：16.59\n对方英雄梯度：28.87"
            },
            {
                "type": "image",
                "content": "/bot_demo_assets/predicted_real_power.png"
            }
        ]

    # 15. Game Time (#时长)
    if "时长" in cmd_full:
        return {
            "type": "text",
            "content": """🎮 示例玩家59 最近2周的游戏时长：
👑 王者荣耀: 14.9h
♨️ Balatro: 31.9h
♨️ Counter-Strike 2: 19.6h
📊 总计时长：78.3h"""
        }

    # Global Overview (#b)
    if cmd_full == "b":
        return {
            "type": "text",
            "content": "机制受益/受害者分析报告生成中...\n示例玩家37：19.426\n示例玩家65：67.24 (重度受害者)"
        }

    # Default message
    return {
        "type": "text",
        "content": f"（电台底噪如夜风拂过麦克风）你刚才提到的 “{cmd_full}”，在数据星图中划出了一道独特的轨迹。 (演示模式)"
    }
