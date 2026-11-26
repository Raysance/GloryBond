# 营地 SDK 接入

营地能力使用私有 `hok-camp-client` 0.8.0，具体提交以gitlink和RELEASE.md为准。SDK独立提供登录、状态、业务查询、对局走势与完整回顾、直播地址及视频帧接口，不依赖本项目或Android。

项目与 SDK 使用同一 Python 3.13 运行版本。SDK CI 只运行一个含 video 扩展的测试任务，仓库检查和构建各执行一次；日常通过仓库提交与固定 gitlink 更新，不创建额外 GitHub Release。

## 会话归属

正式会话位于 `HOK_DATA_DIR/account_sessions/camp-session.json`，权限0600，由SDK读取和保存。Bot/Web只向 `CampClient(state_file=...)` 传路径，不读取token、userKey、完整登录响应或调用 `export_session()`。每次查询前调用 `reload_session()`；同一进程复用实例，保留至少5秒的请求间隔。

管理员登录流程在临时SDK文件中完成扫码和角色选择。原会话继续可用；远端验证、挑战期限和Redis租约均通过后，调用SDK `save_session()` 带旧版本标识原子发布。并发更新时SDK拒绝覆盖，业务配置、玩家映射与.env不写入营地凭据。

旧.env完整会话只在部署时由SDK的 `tools/session/import_saved_session.py` 离线迁移。工具不联网、不打印内容、不覆盖已有目标、不修改源文件。旧营地配置字段不再用于请求。正式会话需作为私有运行数据备份，不能放进公开产物目录。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `src/glorybond/integrations/camp.py` | 计算会话路径，复用SDK客户端，通过公开截图接口保留推进中的直播 |
| `src/glorybond/integrations/wzry.py` | Bot调用入口，记录不含服务端正文的错误类型 |
| `src/glorybond/apps/web/utils.py` | 保持网页业务签名，传SDK会话路径 |
| `src/glorybond/accounts/providers.py` | 登录页面编排，只接收状态和角色标签；SDK保存会话 |
| `src/glorybond/accounts/manager.py` | 授权、限速、挑战期限与租约，成功后触发SDK提交 |
| `src/glorybond/apps/qq/handlers/live_watch.py` | 解析观战目标，先回调阵容再返回新帧，映射安全提示 |
| `src/glorybond/features/game/watch_lineup.py` | 只投影观战响应中的展示字段，使用底蕴/预言模板的缺项留白模式 |
| `src/glorybond/storage/files.py` | 有界读取缓存头像，为阵容图与截图创建独立产物文件名 |
| `src/glorybond/storage/watch_lineups.py` | 按机器人、会话、对局原子入队去重，独立记录投递结果 |
| `tests/test_camp_sdk_boundary.py` | 路径式调用、实例复用、公开接口及协议隔离 |
| `tests/test_event_live_watch.py`、`tests/test_watch_lineup.py`、`tests/test_watch_strength_template.py` | 解析、阵容顺序、缺项留白、去重与回执、会话复用、并发拒绝及安全输出 |

## 业务映射

| 原调用reqtype / 功能 | SDK公开接口 |
| --- | --- |
| btlist / btlist_url | get_battle_list |
| btldetail | get_battle_detail |
| profile / season | get_player_profile / get_current_season |
| heropower / allhero / herostatistics | get_hero_power / get_heroes / get_hero_statistics |
| heroranklist / honorranklist | get_hero_rankings / get_honor_rankings |
| watchbattle（预言阵容） | get_watch_battle_info |
| 观战截图与首次阵容 | capture_watch_frame(on_battle_info=...) |

预言使用阵容资料；截图使用直播视频，不能用流状态替换原阵容返回结构。SDK负责端点、协议、签名、解密、IM等待、心跳和媒体生命周期，宿主不维护任何副本。公开 `capture_watch_frame` 返回状态、固定原因、JPEG、原始阵容快照及复用标记，不返回签名URL。命令使用 `asyncio.to_thread`；同一进程的并发截图立即拒绝，不排队。

`on_battle_info` 在目标身份校验后、等待媒体就绪前收到已有 `battleInfo`，不新增资料查询。回调只向本次独立图片线程提交任务后立即返回，头像下载与绘制不阻塞SDK处理就绪通知和心跳；截图处理返回前等待该任务结束，保证阵容先入队。等待预算仍由SDK遵循本地上限与服务端时限，不因绘图延长。宿主首次在当前会话发送该局阵容；复用底蕴/预言模板，只填昵称、英雄/玩家头像、英雄战力及已有英雄胜负场次之和，其他指标留空，不调用完整底蕴采集流程。使用原模板的 SimHei 字体和头像裁剪；优先读取原有本地英雄头像，其他图片同时加载，最多等待12秒、缓存7天。底色评分仅使用有效的英雄战力、场次、胜率，权重分别为2、1.3、2；战力按 p/(p+5000)、场次按 n/(n+100) 归一后对存在项重新归一权重，不补零，不显示为完整底蕴。红绿和深浅沿用原模板的均值及偏差着色。阵容与截图依次入队，阵容失败不丢弃直播；Redis原子去重一天，QQ明确失败才允许后续手动请求重发，结果未知不重发。

SDK持续解码同一目标的直播，仅保存最新JPEG。重复截图等待本次请求之后的新帧，不重新申请；结束、错误、目标变化、凭据变化及关闭时清理，旧读取器未退出不新建。进程退出通过既有客户端关闭入口清理。首帧可能仍在加载或追赶，本地帧年龄不能推断真实直播延迟。等待就绪通知超时与视频解码错误分别提示；宿主记录固定状态、是否等待超时、复用标记和总耗时，不记录玩家身份、阵容正文或播放地址。

观战结束推送仅在用户回答“是”后启用，宿主用已有 `battleInfo.battleDetailUrl` 的明确战绩参数定位目标，按分钟经共享客户端请求战绩列表；精确匹配已结束记录后，复用个人战绩查询的单局生成和发送流程。没有额外观战申请，也不新增SDK端点。缺少参数时不按时间或最新记录猜测。

## 对局走势与回顾接口

SDK 新增 `get_battle_winning_trend`、`get_battle_replay` 和 `get_battle_analysis`，分别返回本局胜率、经济/经验复盘资料，以及包含可用玩家位置、事件、双方经济的完整回顾。三者独立请求，返回完整业务数据，共用既有会话和限速，不自动联查或补齐采样。

前两项参数与 `get_battle_detail` 相同；完整回顾使用详情 `head.playerId`，不能改用角色 ID 或营地用户 ID。字段与时间单位以私有 SDK 的 [README](https://github.com/Raysance/hok-camp-client#对局走势与完整回顾) 和维护文档为准。SDK 负责协议，宿主接入时仍须经过共享客户端和原有授权，再处理保存及展示。

这次同步依赖仅提供接口能力，现有 Bot/Web 不自动获取这些新资料，也未新增回放页面。新增协议已用 APK/官方公开脚本静态核对及合成数据离线验证，未进行真实对局请求；对局覆盖、隐私和保留期以服务端结果为准。

## 验证与发布

先推送SDK，再更新宿主gitlink并运行DEVELOPMENT.md中的离线检查。部署安装video所需的PyAV；发布不追加真实营地请求或QQ测试消息。SDK已有一次授权的RTMP首帧实测，但不代表任意玩家、整场持续播放或精确直播延迟都已验证。
