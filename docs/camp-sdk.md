# 营地 SDK 接入

营地功能使用私有 `hok-camp-client` 0.4.0，具体提交以主仓库 gitlink 和 RELEASE.md 为准。SDK 可以独立安装或导入；不依赖本项目、NoneBot、Web、Android 或 APK。公开接口及参数说明见 [SDK README](https://github.com/Raysance/hok-camp-client)。

## 职责与文件

| 文件 | 职责 |
| --- | --- |
| `shared/camp.py` | 将旧业务调用名映射到 SDK 命名方法；惰性创建并复用每进程客户端；在同一锁中更新凭据并调用 |
| `hok/api_adapters/wzry.py` | 请求前刷新应用配置，委托 shared.camp，记录脱敏错误类型/码；图片下载委托 SDK |
| `web/utils.py` | 读取最新共享配置并委托同一个适配层；保持既有网页调用签名 |
| `login_console/providers.py` | 登录流程与管理员角色选择编排，仅调用 SDK 公开登录、角色、会话导出和 close 接口 |
| `login_console/store.py` | 应用凭据锁、原子持久化和配置投影编排；营地字段转换委托 SDK |
| `tests/test_camp_sdk_boundary.py` | 检查方法映射、客户端复用、凭据更新、失败不重试和实现边界 |
| `tests/test_wzry_pagination_request.py` | 验证业务分页游标直接交给 SDK |

固定营地端点、HTTP 字段、签名、RSA/XXTEA、响应解码和游戏角色响应归一化均在 SDK。删除 `hok/tools/endecoder.py`、`web/tools/endecoder.py`，不保留兼容副本。角色、阵容或战绩如何用于业务分析与页面展示仍由宿主决定。

## 调用映射

| 原调用 reqtype | SDK 方法 | 返回 |
| --- | --- | --- |
| btlist / btlist_url | get_battle_list | 战绩业务数据，含分页游标 |
| btldetail | get_battle_detail | 对局详情 |
| profile | get_player_profile | 玩家资料 |
| season | get_current_season | 赛季资料 |
| heropower | get_hero_power | 英雄战力 |
| allhero | get_heroes | 英雄资源 |
| herostatistics | get_hero_statistics | 英雄统计 |
| heroranklist | get_hero_rankings | 英雄榜单 |
| honorranklist | get_honor_rankings | 地区荣耀榜 |
| watchbattle | get_watch_battle_info | 完整观战资料，保留现有阵容分析所需字段 |

兼容适配层保留旧调用参数，避免将数据层改造扩大到所有业务函数。新功能优先使用命名 SDK API，不增加新的宿主协议分支。`get_watch_battle_info` 与 SDK 的流状态接口用途不同，不可替换为只返回 URL/state 的方法。

## 会话、错误与限速

应用仍从唯一 `.env` 加载会话与配置，在既有登录锁下原子保存；不把凭据放进源码、日志或公开测试。SDK `from_config/update_config` 接受营地配置段，读取文件、环境变量和数据库仍属于应用。相同配置不重复解析；凭据更新保留请求间隔，失败解析不替换已有实例凭据。

每个 Bot/Web 进程复用一个 SDK 客户端，其营地请求串行且起始间隔至少5秒；两进程之间不共享限速计数。后台登录工作进程继续使用自己的客户端和既有 Redis 授权/限速。SDK 不自动重登或重试，移除旧 Bot 按空结果最多重试三次的行为。

业务非零返回码抛出 `CampError`；网络错误保持网络错误。成功但空的列表/字典保留为空，不能据此认定登录失效。Bot 错误日志只记录业务调用名、异常类型与营地码，不记录请求头、原始响应或签名 URL。用户界面错误处理沿用现有调用方。

## 维护与验证

新增或修改营地协议应在 SDK 完成并验证，再更新本项目 gitlink。SDK 私有实现不得复制入主仓库。SDK 请求契约与响应解密测试只使用合成数据；宿主用 mock 验证委托及返回结构，不再 mock 删除的端点/加密代码。真实账号测试必须另有用户要求，常规回归与发布不追加营地验证请求。

扫码、角色选择、凭据热更新、战绩分页、对局分析、英雄/榜单调用和网页回归均应覆盖。开发命令见 DEVELOPMENT.md；先推送 SDK，再固定提交并推送宿主，防止生产拉取不存在的私有提交。
