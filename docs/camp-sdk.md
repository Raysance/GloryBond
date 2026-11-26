# 营地 SDK 接入

营地能力使用私有 `hok-camp-client` 0.8.0，具体提交以gitlink和RELEASE.md为准。SDK独立提供登录、状态、业务查询、对局走势与完整回顾、直播地址及视频帧接口，不依赖本项目或Android。

## 会话归属

正式会话位于 `HOK_DATA_DIR/account_sessions/camp-session.json`，权限0600，由SDK读取和保存。Bot/Web只向 `CampClient(state_file=...)` 传路径，不读取token、userKey、完整登录响应或调用 `export_session()`。每次查询前调用 `reload_session()`；同一进程复用实例，保留至少5秒的请求间隔。

管理员登录流程在临时SDK文件中完成扫码和角色选择。原会话继续可用；远端验证、挑战期限和Redis租约均通过后，调用SDK `save_session()` 带旧版本标识原子发布。并发更新时SDK拒绝覆盖，业务配置、玩家映射与.env不写入营地凭据。

旧.env完整会话只在部署时由SDK的 `tools/session/import_saved_session.py` 离线迁移。工具不联网、不打印内容、不覆盖已有目标、不修改源文件。旧营地配置字段不再用于请求。正式会话需作为私有运行数据备份，不能放进公开产物目录。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `shared/camp.py` | 计算会话路径，复用SDK客户端，转发业务查询；截图只取首帧并关闭所有连接 |
| `hok/api_adapters/wzry.py` | Bot调用入口，记录不含服务端正文的错误类型 |
| `web/utils.py` | 保持网页业务签名，传SDK会话路径 |
| `login_console/providers.py` | 登录页面编排，只接收状态和角色标签；SDK保存会话 |
| `login_console/manager.py` | 授权、限速、挑战期限与租约，成功后触发SDK提交 |
| `hok/event_handlers/live_watch.py` | 解析观战目标，线程中获取首帧，映射安全提示 |
| `hok/zfile.py` | `save_watch_frame`为每次图片创建独立产物文件名 |
| `tests/test_camp_sdk_boundary.py` | 路径式调用、实例复用、公开接口及协议隔离 |
| `tests/test_event_live_watch.py` | 玩家解析、单张截图、失败关闭、并发拒绝与安全输出 |

## 业务映射

| 原调用reqtype / 功能 | SDK公开接口 |
| --- | --- |
| btlist / btlist_url | get_battle_list |
| btldetail | get_battle_detail |
| profile / season | get_player_profile / get_current_season |
| heropower / allhero / herostatistics | get_hero_power / get_heroes / get_hero_statistics |
| heroranklist / honorranklist | get_hero_rankings / get_honor_rankings |
| watchbattle（预言阵容） | get_watch_battle_info |
| 观战截图 | open_watch_stream → frames → close |

预言使用阵容资料；截图使用实时视频，不能用流状态替换原阵容返回结构。SDK负责端点、协议、签名、解密、IM等待和心跳，宿主不维护任何副本。`capture_watch_frame`只返回状态、固定原因或JPEG，不向QQ或Web回传签名URL。命令使用 `asyncio.to_thread`；同一进程的重复截图不会排队请求。

## 对局走势与回顾接口

SDK 新增 `get_battle_winning_trend`、`get_battle_replay` 和 `get_battle_analysis`，分别返回本局胜率、经济/经验复盘资料，以及包含可用玩家位置、事件、双方经济的完整回顾。三者独立请求，返回完整业务数据，共用既有会话和限速，不自动联查或补齐采样。

前两项参数与 `get_battle_detail` 相同；完整回顾使用详情 `head.playerId`，不能改用角色 ID 或营地用户 ID。字段与时间单位以私有 SDK 的 [README](https://github.com/Raysance/hok-camp-client#对局走势与完整回顾) 和维护文档为准。SDK 负责协议，宿主接入时仍须经过共享客户端和原有授权，再处理保存及展示。

这次同步依赖仅提供接口能力，现有 Bot/Web 不自动获取这些新资料，也未新增回放页面。新增协议已用 APK/官方公开脚本静态核对及合成数据离线验证，未进行真实对局请求；对局覆盖、隐私和保留期以服务端结果为准。

## 验证与发布

先推送SDK，再更新宿主gitlink并运行DEVELOPMENT.md中的离线检查。部署安装video所需的PyAV；发布不追加真实营地请求或QQ测试消息。SDK已有一次授权的RTMP首帧实测，但不代表任意玩家、整场持续播放或精确直播延迟都已验证。
