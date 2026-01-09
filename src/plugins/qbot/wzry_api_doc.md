# wzry_get_official API 文档

`wzry_get_official` 函数用于获取王者荣耀官方数据。

## 函数签名

```python
def wzry_get_official(reqtype: str, **kwargs) -> dict:
    """
    获取王者荣耀官方数据接口
    
    Args:
        reqtype (str): 请求类型
        **kwargs: 动态参数，取决于 reqtype
            - openid (str): 用户OpenID
            - roleid (str): 角色ID
            - serverid (str): 服务器ID
            - gameSeq (str): 对局序列号 (btldetail需要)
            - gameSvrId (str): 游戏服务器ID (btldetail需要)
            - relaySvrId (str): 中继服务器ID (btldetail需要)
            
    Returns:
        dict: 响应数据字典
    """
    ...
```

## 参数说明

- `reqtype` (str): 请求类型。可选值如下：
    - `btldetail`: 单局详细战绩
    - `btlist`: 历史战绩列表
    - `heropower`: 英雄战力列表
    - `heroranklist`: 英雄榜单（全服/分路）
    - `herostatistics`: 英雄综合数据统计
    - `profile`: 个人主页/账号信息

## 返回值结构

返回值均为 JSON 格式的字典。以下是各 `reqtype` 的通用返回结构定义。

### 1. btldetail (单局详细战绩)

获取指定对局的详细数据，包括双方队伍信息、出装、KDA等。

**返回结构:**

```json
{
  "head": {
    "gameResult": "boolean", // 比赛结果 (false: 负, true: 胜)
    "acntCamp": "int",       // 己方阵营 (1: 蓝方, 2: 红方)
    "mapName": "string",     // 地图名称 (e.g. "巅峰赛")
    "gradeGame": "string",   // 评分
    "kda": "string",         // KDA
    "killCnt": "int",        // 击杀数
    "deadCnt": "int",        // 死亡数
    "assistCnt": "int",      // 助攻数
    "roleId": "string",      // 角色ID
    "roleName": "string",    // 角色名
    "heroId": "int",         // 英雄ID
    "heroName": "string",    // 英雄名
    "is10v10": "boolean"     // 是否10v10模式
  },
  "battle": {
    "gameType": "int",       // 游戏类型ID
    "usedTime": "int",       // 游戏时长(秒)
    "dtEventTime": "string", // 结束时间 (MM-DD HH:mm)
    "startTime": "string"    // 开始时间 (MM-DD HH:mm)
  },
  "redTeam": { // 红方队伍信息
    "acntCamp": "int",       // 阵营ID
    "banHeros": [ // 禁用英雄列表
        {
            "heroId": "int",       // 英雄ID
            "heroName": "string",  // 英雄名
            "heroIcon": "string"   // 英雄头像URL
        }
    ], 
    "list": [ // 玩家列表
        {
            "roleId": "string",    // 角色ID
            "heroId": "int",       // 英雄ID
            "heroName": "string",  // 英雄名
            "kda": "string",       // KDA
            "killCnt": "int",      // 击杀数
            "deadCnt": "int",      // 死亡数
            "assistCnt": "int",    // 助攻数
            "equipList": [ // 出装列表
                {
                    "equipId": "int",      // 装备ID
                    "equipName": "string", // 装备名
                    "equipIcon": "string"  // 装备图标URL
                }
            ]
        }
    ]
  },
  "blueTeam": { // 蓝方队伍信息
      // 结构同 redTeam
  }
}
```

### 2. btlist (历史战绩列表)

获取玩家最近的比赛记录列表。

**返回结构:**

```json
{
  "list": [
    {
      "dtEventTime": "string", // 时间戳 (秒)
      "gametype": "int",       // 游戏类型
      "winCamp": "int",        // 获胜阵营
      "gametime": "string",    // 游戏时间 (HH:mm)
      "killcnt": "int",        // 击杀
      "deadcnt": "int",        // 死亡
      "assistcnt": "int",      // 助攻
      "gameresult": "int",     // 比赛结果 (1:胜, 2:负)
      "heroId": "int",         // 英雄ID
      "AcntCamp": "int",       // 己方阵营
      "mapName": "string",     // 地图/模式名
      "gameSeq": "string",     // 对局唯一序列号 (用于查询 btldetail)
      "gameSvrId": "string",   // 服务器ID
      "relaySvrId": "string",  // 中继服务器ID
      "roleJobName": "string", // 段位名称
      "stars": "int",          // 星数
      "heroIcon": "string"     // 英雄头像URL
    }
  ],
  "isGaming": "boolean",          // 是否正在游戏中
  "bubbleTips": "object|null",    // 气泡提示对象
  "gameVideoTips": "object|null", // 视频提示对象
  "stickyBattle": "object|null",  // 置顶对局对象
  "bubbleTipsList": ["object"]    // 气泡提示列表
}
```

### 3. heropower (英雄战力列表)

获取玩家所有英雄的战力信息。

**返回结构:**

```json
{
  "heroList": [
    {
      "basicInfo": {
        "heroId": "int",         // 英雄ID
        "winNum": "int",         // 胜场
        "failNum": "int",        // 负场
        "playNum": "int",        // 总场次
        "winRate": "string",     // 胜率 (e.g. "51.0%")
        "heroFightPower": "int", // 英雄战力
        "title": "string",       // 英雄名
        "alias": "string",       // 称号
        "heroIcon": "string"     // 头像URL
      },
      "honorTitle": "object|null" // 荣耀称号 (如: 省标、国标等)，无称号为 null
    }
  ]
}
```

### 4. heroranklist (英雄榜单)

获取全服或分路的英雄数据榜单（胜率、登场率等）。

**返回结构:**

```json
{
  "filter": {
    "branchFilter": ["string"], // 分路筛选选项列表
    "tabFilter": ["string"],    // 标签筛选选项列表
    "eventList": ["string"]     // 事件列表
  },
  "updateTime": "string",       // 数据更新时间 (YYYYMMDD)
  "list": [
    {
      "heroId": "int",          // 英雄ID
      "banRate": "number",      // 禁用率
      "showRate": "number",     // 登场率
      "winRate": "number",      // 胜率
      "tRank": "string",        // T度排名 (e.g. "T0", "T1")
      "goldPlay": "number",     // 金牌率
      "heroInfo": {
        "heroId": "int",        // 英雄ID
        "heroName": "string",   // 英雄名
        "heroCareer": "string", // 职业 (e.g. "战士/坦克")
        "heroIcon": "string"    // 头像URL
      }
    }
  ]
}
```

### 5. herostatistics (英雄综合数据统计)

获取玩家特定英雄的详细统计数据，包括场次、胜率、荣耀称号等。与 `heropower` 类似但可能包含更多统计维度。

**返回结构:**

```json
{
  "heroList": [
    {
      "basicInfo": {
        "heroId": "int",         // 英雄ID
        "winNum": "int",         // 胜场
        "failNum": "int",        // 负场
        "playNum": "int",        // 总场次
        "winRate": "string",     // 胜率
        "heroFightPower": "int", // 英雄战力
        "title": "string",       // 英雄名
        "heroIcon": "string"     // 头像URL
      },
      "honorTitle": { // 荣耀称号详情
        "heroId": "int",         // 英雄ID
        "rank": "int",           // 排名
        "type": "int",           // 称号类型
        "region": {
          "provinceName": "string", // 省份
          "cityName": "string",     // 城市
          "countyName": "string"    // 区县
        },
        "desc": {
          "abbr": "string",      // 简称 (e.g. "县级第21嫦娥")
          "full": "string"       // 全称
        }
      }
    }
  ]
}
```

### 6. profile (个人主页/账号信息)

获取玩家的基本信息、段位、在线状态等。

**返回结构:**

```json
{
  "targetRoleId": "string",     // 目标角色ID
  "userId": "string",           // 用户ID
  "roleList": [
    {
      "roleId": "string",       // 角色ID
      "roleName": "string",     // 角色名
      "roleIcon": "string",     // 头像URL
      "gameLevel": "int",       // 等级
      "gameOnline": "int",      // 在线状态 (1:在线, 2:离线?)
      "areaId": "int",          // 大区ID
      "serverId": "int",        // 服务器ID
      "roleJobName": "string",  // 段位名
      "serverName": "string",   // 服务器名
      "roleText": "string",     // 大区描述 (e.g. "安卓手Q363区")
      "battleId": "string"      // 当前/最近对局ID
    }
  ],
  "head": {
    "modsStr": "string", // 模块ID列表字符串
    "mods": [
      {
        "stype": "int",      // 样式类型
        "ltype": "int",      // 布局类型
        "modId": "int",      // 模块ID (e.g. 202: 皮肤)
        "icon": "string",    // 图标URL
        "name": "string",    // 模块名称 (e.g. "皮肤", "英雄")
        "content": "string", // 显示内容 (e.g. "450/754")
        "jumpUrl": "string", // 跳转链接
        "param1": "string",  // 参数1
        "param2": "string",  // 参数2
        "param3": "string",  // 参数3
        "showStyle": "int"   // 显示样式
      }
    ]
  },
  "bgImg": "string",     // 背景图URL
  "gameBgImg": "string"  // 游戏背景图URL
}
```
