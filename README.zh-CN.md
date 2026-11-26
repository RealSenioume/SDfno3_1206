[English](README.md) | 简体中文

# 又一个LOLping样子的DSH插件

一个 Windows 11 桌面端的"标记轮盘"叠加层，视觉风格参考《英雄联盟》的 ping 轮盘。
按住一个修饰键和鼠标键，朝八个带标签的扇形之一拖动，然后松开。轮盘关闭，一段短促的
爆裂动画确认你的选择，这次标记被追加到本地日志文件。

**lolping 不是游戏内工具。** 它不读写《英雄联盟》的内存，不注入游戏进程、不与游戏进程
通信，不使用 Riot API，也不建立任何网络连接。它只是一个普通的桌面叠加层：在鼠标位置
画一个半透明轮盘，并把用户选中的标记记录到本地 JSONL 文件。

本项目不附带任何第三方美术或音频资源。扇区图标是 `src/lolping/assets.py` 里用
`QPainterPath` 生成的原创矢量图形，音效由 `src/lolping/sounds.py` 实时合成，因此仓库中
不含任何 Riot Games 素材，也没有二进制媒体文件。

- 版本：**0.4.0**
- 平台：**Windows 11**（64 位）
- 运行时：**Python 3.14**、**PyQt5 5.15.11**、**pynput 1.8.2**
- 无其他运行时依赖，运行期间不访问网络
## 下载

**Windows v0.4.0** —— `lolping-0.4.0-win64.zip`，36.7 MB，SHA-256
`e9899201e32243bbb8d1bfc5ceabe425f7172917eecd4dac16daaaf7ed232a3f`。
解压到一个空文件夹后运行 `lolping\lolping.exe`，`_internal` 文件夹必须与它同级。
exe 未签名，Windows SmartScreen 可能要求确认。

- [下载 lolping-0.4.0-win64.zip](release/lolping-0.4.0-win64.zip)



## 功能

- **Jarvis 数据仪表主题**（v0.4.0 唯一外观）：三条旋转的观测窗口覆盖烘焙的香港等高线、
  地标与等温线带；地标名沿弧线排布并带经纬度微标签；PCB 风格走线、外环之外的遥测带，
  以及实时从桌面抓取的真实磨砂玻璃背景。
- 八扇区径向菜单，通过"按住并拖动"的手势在鼠标位置展开（默认：按住 **Alt + 鼠标左键**）。
  不拖动的单击发送中央（基础）ping；在死区内松开、按 **Esc** 或点击其他鼠标键则取消。
- 默认扇区（从 3 点钟方向顺时针）：On My Way、All-In、Assist Me、Need Vision、
  Enemy Missing、Enemy Vision、Danger、Push。八个扇区都可重命名，每个扇区都有矢量图标，
  并可用自定义 PNG 替换。
- 提交编排：圆环向所选扇区收缩，环内容在形状保持的同时淡出，扇区名称弹出，中心播放
  标记爆裂动画。
- 四个合成音效：展开、悬停咔哒、提交铃音、取消下滑音。声音默认关闭，音量默认 50%。
- **DSH 模式**（设置 → DSH mode）：没有注入功能的扇区会被淡化且无法选中。注入的扇区是
  **Enemy Missing**（区域截图）与 **On My Way**（画面搜索）；悬停搜索扇区时会显示
  640×360 截图框与 320×180 OCR 判定框。
- **意图管线**：每次注入扇区的提交都会向
  `%APPDATA%\lolping-desktop\intents.jsonl` 追加一行 JSON；截图动作还会在 `regions/`
  下保存一张 640×360 PNG。
- **On My Way 文本搜索**：截取中心 320×180 区域，调用离线 Windows OCR（不联网），
  对识别行做中心加权与 0–100 可用性评分，再在默认浏览器中打开文本搜索
  （≥60 文本搜索；25–60 文本搜索并把截图放入剪贴板；<25 为下一里程碑的图片搜索路径）。
- **设置窗口**：夜间模式、**Apply** 不关闭窗口，以及 280×280 的实时轮盘预览——预览下方
  是实时抓取并模糊的桌面。预览循环播放唤醒/选择/退出动画，桌面轮盘出现时自动暂停。
- 可配置触发方式（Ctrl/Alt/Shift/Win 加左/右/中/X1/X2 鼠标键）、轮盘半径、死区、
  Jarvis 背景不透明度、图标大小/标签、标记时长、声音、暂停热键与开机启动。
- 半透明、无边框、始终置顶的轮盘，不会从下层窗口抢走焦点；每块显示器一个叠加层，
  显示在光标所在屏幕；单实例运行。
- 托盘菜单（设置、标记历史、配置目录、暂停/恢复、退出）、本地 JSONL 日志与可选的延迟
  测量模式；配置读取容错。
- **DSH 插件骨架** `plugin/lolping-intents`：把意图日志暴露为 `lolping_intents` 工具并
  跟踪新记录，agent 可以读取截图。

## 快速开始

```powershell
git clone https://github.com/RealSenioume/SDfno3_1206
cd SDfno3_1206

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:PYTHONPATH = "src"   # 直接从源码运行，无需安装
python -m lolping
```

已经有代码了？跳过前两行，直接 `cd` 进入包含 `src`、`requirements.txt` 和
`pyproject.toml` 的目录。

程序会常驻系统托盘。按住 **Alt**，按下并保持**鼠标左键**，从光标位置向外拖动，
在想要的扇区上松开。要取消：按 **Esc**、点鼠标右键，或在死区内松开。退出可从托盘菜单
；按 **Ctrl+Shift+Q** 暂停或恢复标记。退出请用托盘菜单。

打包成可执行文件的方法见 `docs/07-build-and-release.md`。

## 发送一次标记

1. 按住 **Alt** 并按下**鼠标左键**。轮盘在光标处出现。
2. 从中心向外拖动。光标下的扇区会被强调，图标放大，名称显示在中心。
3. 松开鼠标键即提交。轮盘中心绘制一段爆裂动画，同时向 `pings.jsonl` 写入一行记录。
4. 取消：在死区内（默认 34 px）松开、按 **Esc**，或在轮盘打开时点鼠标右键。

| 扇区 | 时钟位置 | 默认标签 | 默认图标 |
| --- | --- | --- | --- |
| 0 | 3 点钟 | On My Way | `on_my_way` |
| 1 | 4:30 | All-In | `all_in` |
| 2 | 6 点钟 | Assist Me | `assist` |
| 3 | 7:30 | Need Vision | `vision` |
| 4 | 9 点钟 | Enemy Missing | `missing` |
| 5 | 10:30 | Enemy Vision | `enemy_vision` |
| 6 | 12 点钟 | Danger | `danger` |
| 7 | 1:30 | Push | `push` |

图标 id `danger` 和 `generic` 同样可用，可在设置中指派给任意扇区。自定义 PNG 可以替换
某个扇区的图标；详见 `docs/05-user-manual.md`。

## 命令行

```text
python -m lolping [--config PATH] [--latency-probe] [--debug] [--self-test]
```

| 参数 | 含义 |
| --- | --- |
| `--config PATH` | 使用 `PATH` 代替 `%APPDATA%\lolping-desktop\config.json`。 |
| `--latency-probe` | 每次手势向 `latency.jsonl` 写入一行（`frame_ms`、`commit_ms`）。用于测量，不适合日常使用。 |
| `--debug` | 输出详细的诊断日志。 |
| `--self-test` | 运行内置的无界面自检后退出，安装后可用于验证。 |

## 文件

所有用户数据位于 `%APPDATA%\lolping-desktop\`：

| 文件 | 内容 |
| --- | --- |
| `config.json` | 设置窗口保存的配置。首次保存时创建；读取时容错。 |
| `pings.jsonl` | 每次提交的标记一行 JSON：`ts`、`sector`、`name`、`x`、`y`。 |
| `intents.jsonl` | DSH 模式下每次注入提交一行 JSON：扇区、动作、区域、截图路径、OCR 文本/分数/模式。 |
| `regions/` | 注入动作保存的 PNG 截图（`region-*.png`、`search-*.png`）。 |
| `latency.jsonl` | 仅在 `--latency-probe` 时写入：`ts`、`frame_ms`、`commit_ms`。 |
| `lolping.log` | 滚动写入的诊断日志；反馈问题时请附上。 |

## 文档

| 文档 | 用途 |
| --- | --- |
| `docs/00-interfaces.md` | 冻结的模块接口契约（内部使用）。 |
| `docs/01-proposal.md` | 问题、目标、范围、技术选型、风险、计划。 |
| `docs/02-requirements.md` | 用户故事、功能与非功能需求、用例。 |
| `docs/03-design.md` | 设计理由与模块说明（维护者阅读）。 |
| `docs/04-test-plan.md` | 测试策略、矩阵、测试用例、测量协议。 |
| `docs/05-user-manual.md` | 安装、手势、设置项参考、故障排查。 |
| `docs/06-report-outline.md` | 最终报告的大纲与证据计划。 |
| `docs/07-build-and-release.md` | 打包与发布步骤。 |
| `docs/08-report-draft.md` | 报告正文草稿，未测量的数字标记为 TBD。 |
| `docs/10-dsh-plugin.md` | DSH 插件骨架、安装/验证步骤与限制。 |
| `docs/09-roadmap.md` | 活路线图：现在 / 接下来 / 更远，含 DSH 插件与多人协作研究（中文版：`docs/09-roadmap.zh-CN.md`）。 |

## 已知限制

- **独占全屏。** Windows 桌面叠加层通常无法显示在独占全屏应用之上。若需要看到轮盘，
  请以无边框或窗口化模式运行游戏。
- **管理员权限窗口。** 在 Windows 的用户界面特权隔离（UIPI）下，普通权限的 lolping
  无法绘制在管理员权限窗口之上，也收不到这些窗口的输入。必要时请以相同或更高的完整性
  级别运行 lolping。
- **全局输入钩子。** 部分安全软件会限制全局鼠标/键盘钩子。lolping 会监控并重启失效的
  监听器，但可能需要在安全软件中将其加入白名单。
- **触发冲突。** Alt + 鼠标左键被一些应用用作自己的快捷键。触发方式可配置，请在设置中
  更改。
- **声音不叠加。** Windows 的 `winsound` API 一次只能异步播放一个声音，因此新的音效会
  打断上一个。对于短音效而言这是刻意的取舍，不是缺陷。
- **图片搜索。** On My Way 目前打开文本搜索；截图/图片搜索档位（M2）尚未发布。
- **DSH 插件。** `plugin/lolping-intents` 只是骨架：把意图日志暴露为工具，但还不会
  自动发起 agent 回合，也不写回结果；请通过 DSH bundle installer 安装。
- **范围。** 仅支持 Windows；v0.4.0 固定为八个扇区；不具备游戏感知能力；没有队伍或房间
  功能；不支持跨平台。

## 许可证

MIT 许可证。见仓库根目录的 `LICENSE` 文件。

## Riot Games 免责声明

此 lolping 未获得 Riot Games 的认可，也不代表 Riot Games 或任何正式参与制作或管理
《英雄联盟》的人士的观点或意见。《英雄联盟》与 Riot Games 是 Riot Games, Inc. 的商标
或注册商标。
