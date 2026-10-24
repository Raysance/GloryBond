# 原应用 UI 资源核对

分析材料为《王者荣耀》Android 12.1.1.1 APK，SHA-256 为 `d0b617eb7327bd6856948dc112e5fb1d55617bc1a02e1dcfc307172f1b25a6e3`。安装包和完整分析输出不随机器人分发。

## 字体

下列文件从原 APK 对应 ZIP 成员直接提取，未转换字形。字体内部名称经 TTF name 表核对。

| 文件 | APK 成员 | 字体内部名称 | SHA-256 |
| --- | --- | --- | --- |
| fonts/Ex_GameFontYaHei.ttf | assets/fonts/Ex_GameFontYaHei.ttf | FZLanTingHeiS-R-GB | `5301bdfe967da491eec7edf29c6ba50cf44f27ad30a0d70a7f74247f3656199b` |
| fonts/Ex_GameFont.ttf | assets/fonts/Ex_GameFont.ttf | FZZhengHeiS-DB-GB | `37a7daf35e706b609d5e34cead9f37ab26ccf7362d76c3f791c4eb464fdf01b2` |

渲染器的普通/粗体分别使用以上两个文件。原图固定文字继续沿用模板；动态内容使用原应用字形。选用原字体不等于已证明所有控件的字体选择、字号和描边参数完全复现。

## 布局

已读取原生玩家资料页 Form_Player_Info.asset，提取副本 SHA-256 为 `cda96073d65238cd70cf09c4cc07ad8f99470937dfaffd7de4548b65ffae6d01`，QTS 资源 hash 为 `0xe597575f9f84cead`。已有提取记录指向 APK builtin/9；该副本的压缩页记录与存储摘要未在本轮重新认证，布局结论限于所读取的资源副本。

资源使用 Unity 2022.3.5f1 定制序列化格式，类型记录省略 type-tree blob，但保留依赖数组。只在离线解析时跳过空缺的树读取，再使用 Unity 内建类型定义读取 GameObject / RectTransform；不把这条规则应用到业务运行时或任意其他资源。

已解析 536 个 GameObject 和 530 个 RectTransform，获得控件名称、父子路径、局部位置、缩放、锚点、尺寸和 pivot。2492 个对象中共 1570 个可读，922 个自定义脚本或其他组件仍未解析。这些数据证明可以提取布局结构，不能据此声称已恢复所有字体参数和页面。

该根表单包含 `Center/pnlBg/pnlBody/MatchHonor` 等挂载节点，英雄荣誉和对战资料的完整子表单还需分别还原。当前三张报告继续使用用户提供截图的精确列坐标和模板比例，不能把根表单的局部坐标当作截图绝对像素。
