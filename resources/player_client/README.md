# 玩家客户端界面模板

hero.jpg、game.jpg、heroes.jpg 是用户提供的三张游戏截图，分别用于个人荣誉、对战资料和英雄列表界面。只作为静态模板保存。gen_player_client.py 在发送前清除示例统计、标签、卡片、分路段位和雷达填充，再写入真实查询的白名单字段；第二行示例英雄也必须清除。

未取得的字段仅以“—”或空雷达框占位，具体缺项只在图外文字说明，不能将原截图中的数字留作真实结果。卡片图片、名称和统计栏使用同一组精确列坐标；英雄列表使用官方 mobileskin 立绘居中裁切，新英雄使用官方默认插画；小乔个人荣誉沿用原模板的同一默认形象。缓存不保存到此目录。

0.6.16 页面视图补充原生评分/雷达、使用中的赛年标签、历史徽章次数、历史称号名次、战斗风格和分路段位。游戏显示值来自分路加权 display，不能以原始汇总行替代；英雄荣誉采用自己的原生分母和评分转换。图中不添加解释性文案。

动态文字使用原应用随包字体，常规字重为 Ex_GameFontYaHei.ttf（FZLanTingHeiS-R-GB），粗体为 Ex_GameFont.ttf（FZZhengHeiS-DB-GB）。字体路径分别由 PlayerClient.report_font_path / report_bold_font_path 配置，经 zfile.player_client_report_font() 加载，不依赖主机字体。固定文字保留截图字形。来源和布局提取范围见 [native-ui.md](native-ui.md)。
