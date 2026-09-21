# ISY5002 · 三路段交通图像采集

当前配置采集实时接口可用的 8 个摄像头，覆盖 Causeway、Second Link 和 Sentosa
Gateway 三个路段组。采集方式沿用旧项目：定时请求 API、下载图片、保存每轮记录。
本仓库最初只采 Sentosa，因此仓库名称保留 `ISY5002-Sentosa-Traffic`。
当前尚未运行 YOLO 或训练模型。

## 本周采集计划

| 参数 | 设置 |
|---|---|
| 开始时间 | 2026-09-14 周一 00:21，新加坡时间 |
| 结束时间 | 2026-09-21 周一 00:00，新加坡时间，不含该时刻 |
| 间隔 | 每 10 分钟一轮，全天 24 小时 |
| 计划轮次 | 1,006 轮；无缺帧时最多 8,048 张 |
| 数据目录 | `data/week-20260914/` |
| 配置文件 | `reference/collection_week.json` |

时间窗口使用带 `+08:00` 的 ISO 时间戳。对应 UTC 起止为
2026-09-13 16:21 到 2026-09-20 16:00。最后一个正常计划采样点是
2026-09-20 23:51 新加坡时间。结束日期不变，开始比最初计划推迟 21 分钟。

| 路段组 | CameraID | 点位 |
|---|---|---|
| causeway | 2701 / 2702 / 2704 | Woodlands Causeway / Checkpoint / Flyover |
| second_link | 4703 / 4712 / 4713 | Tuas Second Link / After Tuas West Road / Checkpoint |
| sentosa_gateway | 4798 / 4799 | 朝 Telok Blangah / 朝 Sentosa |

这里“新 8 个”指本次重新采集的集合，其中前 6 个与旧研究集合重叠。
根据当前请求，已移除脚本的旧摄像头排除逻辑。旧研究的 2706、4707 当前未返回。
原先的 Sentosa 两点配置保留在 `reference/camera_sentosa.csv`。

官方说明从 2026-06-30 起，仅保留关卡及部分连接道路和 Sentosa Gateway 的服务。
[公告](https://onemotoring.lta.gov.sg/content/onemotoring/home/digitalservices/view-traffic-cameras.html)。
这是三个研究路段组，不代表每张图只包含一个行车方向。

## 检查配置与试采

Python 3.11+，macOS/Linux；程序只使用标准库。
在本仓库根目录运行：

```bash
python3 scripts/run_collection_week.py --check
python3 scripts/run_collection_week.py --once
```

`--check` 只显示计划；`--once` 立即试采一轮，并保存到独立的
`data/trial-eight-cameras/`，不会混入正式一周的数据。

## 本机或服务器运行

```bash
python3 scripts/run_collection_week.py
```

可以在开始时间前启动，程序会等待到 9 月 14 日 00:21；每 10 分钟采集一次，
9 月 21 日 00:00 停止。若中途启动，先请求当前图像，再对齐下一采样时刻；
不会把当前图像伪装成错过时刻的历史数据。重启不会推迟计划结束日期。

macOS 保持前台运行并防止空闲睡眠：

```bash
caffeinate -i python3 scripts/run_collection_week.py
```

必须保持供电、联网，终端进程不可退出；合盖仍可能影响运行。Ctrl+C 停止。
单个输出目录只允许一个采集进程写入。软件调度和网络均存在延迟，因此时间戳记录
实际采集时刻与源图片时刻，而非声称硬实时精度。

## 按旧项目方式使用 GitHub Actions

工作流 `Collect eight traffic cameras` 已于 2026-09-13 启用，仓库变量
`COLLECTION_ENABLED=true`，按上述 9 月 14–21 日窗口采集。
本仓库的默认行为仍是：未设置该变量时关闭持续排程。
本机不需要一直开机；不需要 AWS。图片保存到 GitHub Actions artifact，保留 30 天。

启用步骤：

1. 确认默认分支上的 `reference/collection_week.json` 是上述一周计划。
2. 到 Settings → Secrets and variables → Actions → Variables 新建
   `COLLECTION_ENABLED`，值为 `true`。
3. 到 Actions 查看运行记录。手动运行的 `mode` 默认 `chain`，启动一个自续接的
   长采集窗口；`sample` 补采一轮；`batch` 配合 `duration_minutes` 采集最多 55 分钟；
   `trial` 采一轮但写到试采目录，不进入正式数据集。
4. 停止后续排程，把 `COLLECTION_ENABLED` 改为 `false`。已有运行需在 Actions 中取消。

也可以执行：

```bash
# 启用持续排程（public 仓库标准 runner 免费）
gh variable set COLLECTION_ENABLED --body true --repo waiwai033/ISY5002-Sentosa-Traffic
# 关闭后续排程
gh variable set COLLECTION_ENABLED --body false --repo waiwai033/ISY5002-Sentosa-Traffic
```

### 为什么不靠 cron

实测这个仓库的 GitHub cron **极不可靠**：

| cron | 机会 | 实际派发 |
|---|---|---|
| `0 21,2,7,12 * * *` | 12:00Z | 12:28Z（迟 28 分钟）|
| `0 16,22,4,10 * * *` | 16:00Z | **未派发**（提前 3h23m 就注册好了）|
| `21 * * * *` | 16:21Z | 未派发 |
| `1,11,21,31,41,51 * * * *` | 9/13 17:00Z–9/14 00:54Z 约 42 次 | **仅 3 次**（19:10、21:25、23:17）|

到达率约 7%，而 `workflow_dispatch` 手动触发至今 **100% 成功**。
按每次 12 分钟的短窗口算，7 小时里只覆盖了约 8% 的时间 —— cron 不能作为主要触发方式。

### 自续接长窗口

每次运行连续采集最多 **340 分钟**（可用仓库变量 `CHAIN_BATCH_MINUTES` 调整，
上限 350；GitHub 单任务硬上限 6 小时），内部由 `next_tick` 对齐到 9/14 00:21 的
10 分钟网格，**完全不依赖 cron 的定时精度**。
运行结束前，用 `GITHUB_TOKEN` 调 `gh workflow run` 派发下一个窗口。
一周只需约 28 次接力，而不是 1,008 次 cron 触发。

> `GITHUB_TOKEN` 触发的事件通常不会产生新的 workflow run，但 `workflow_dispatch`
> 和 `repository_dispatch` 是明确的例外。本仓库已实测验证：探针派发后 8 秒，
> 新的 run 正常创建并成功执行。

cron 保留为**看门狗**，它**不采集任何数据**，只回答一个问题：当前还有没有活着的采集运行？
没有就派发一个新链路，有就立刻退出，整个检查几秒钟完成。

> 早期版本让排程运行直接采集、并和链路共享同一个 concurrency group，
> 结果排程运行会 pending 卡住整整 5 个多小时，还会抢在链路自己的交棒前面启动
> （run #14 就是这样被卡了 7 分钟后手动取消的）。
> 现在看门狗有独立的 concurrency group，永远不会排在采集后面。

防失控的四道闸：

1. 只在采集窗口内派发后继，9/21 之后自动停
2. 运行不足 **30 分钟**不派发 —— 崩溃的窗口不会变成高速空转循环
3. 每个窗口只派发一个后继，不会增殖；chain 类运行共享同一个 concurrency group，
   同时最多 1 跑 1 等
4. `COLLECTION_ENABLED` 设为 `false` 会让下一个链接被跳过，链路随即终止

本仓库已转为 **public**，标准 runner 的运行分钟与附件存储均免费。
参考量级：8 台摄像头约 1.60 MB/轮，一周原始 JPEG 约 1.61 GB。
见 [GitHub 额度与限制](https://docs.github.com/en/actions/reference/limits)。

manifest 记录的始终是真实请求时间，采样时刻以 manifest 为准。

下载附件并及时归档：

```bash
# 单次运行
gh run download RUN_ID --repo waiwai033/ISY5002-Sentosa-Traffic --dir data/github/RUN_ID
# 一次性取回全部采样附件，图片按 images/<camera_id>/<拍摄时间>.jpg 自然合并
gh run download --repo waiwai033/ISY5002-Sentosa-Traffic --dir data/github/all
```

不同 Actions 批次各自保存 manifest 和状态；合并时按 `camera_id + sha256` 去重，
不把多个不同摄像头的相似画面当成同一观测。附件应在 30 天内下载。

## 获取采集的数据

采集分成约 30 个 GitHub 窗口跑完，图片散在几十个 artifact 里、各带一份 manifest。
一条命令合并成单一数据集：

```bash
python3 scripts/fetch_dataset.py
```

它会下载全部未过期 artifact（缓存在 `data/github/all/`，重复运行跳过已下载的），
按文件名合并去重，产出：

```
data/dataset/
├── README.md           # 数据集说明，含观测数与文件数的逐步对账
├── manifest.csv        # 全部观测合并，按 (collected_at, camera_id) 去重
├── images/<camera_id>/<拍摄时间>_<id>_<时分>_<哈希>.jpg
└── gallery/            # 相册，见下节
```

其中 `README.md` 由脚本按实际数据现算生成（不是写死的），解释了
**为什么观测记录数多于图片数** —— 一行记录是一次请求，一个文件是一帧不重复画面，
差额来自 `stale` / `duplicate` / `missing` / `error` 以及重叠窗口重复取到的同一帧。

同一帧在不同窗口里文件名和内容完全相同，复制时自然覆盖，不会重复计数。

常用参数：`--skip-download` 只合并已缓存的；`--out` 换输出目录；`--cache` 换缓存位置。

## 浏览已采集的图像

```bash
python3 scripts/build_gallery.py          # 读 data/dataset，写 data/dataset/gallery
python3 -m http.server 8791
```

然后访问 http://localhost:8791/data/dataset/gallery/index.html

相册放在数据集内部，备份或转移数据集时会一并带走。
（必须走 HTTP，浏览器不允许 `file://` 页面读取同目录以外的图片。）

功能：按摄像头、日期、时段（夜间/早晚高峰/白天）筛选；**网格**视图按日分组、
缩略图懒加载、点击放大；**时间轴**视图把某台摄像头的序列当延时片播放，
支持 ← → 单帧步进和空格播放暂停。每帧标注拍摄时间和**帧龄**
（拍摄到采集的间隔），帧龄超过 20 分钟标橙色，便于识别静止时段。

缩略图由 macOS 自带的 `sips` 生成（约 23 KB/张），原图按需加载。
重复运行只补新增帧。7,321 帧约需 100 秒。

## 数据来源与密钥

默认使用 [data.gov.sg 实时交通图像接口](https://api.data.gov.sg/v1/transport/traffic-images)，
目前已实测无 Key 可采。依据[官方说明](https://guide.data.gov.sg/developer-guide/api-overview)，
无 Key 可用于测试，持续采集建议申请并配置 `DATA_GOV_SG_API_KEY`：本机放环境变量，
GitHub 放同名 Actions Secret。不要把 Key 放入代码；`.env` 不会自动加载。

也保留了旧项目的 LTA DataMall `Traffic-Imagesv2` 路径：把配置中的 `source` 改为
`lta` 并设置 `LTA_API_KEY`。LTA 带 Key 路径仅做过模拟测试，当前没有凭据进行实测。
不自动切换数据来源。`.env.example` 说明了变量名称。

## 文件与数据质量

正式数据保存为：

```text
data/week-20260914/
  images/<camera-id>/*.jpg
  metadata/*.json
  manifest.csv
  state.json
```

- CSV 每轮每台摄像头一行，记录路段组、方向、源图像时间、采集时间、UTC/SGT、
  SHA256、字节数、路径和状态。
- 状态：downloaded / duplicate / missing / stale / error。请求失败自动重试。
- 同一内容重复返回时保留记录并复用文件；不强行凑足 8,048 张。
- data.gov.sg 使用源图片时间；超过 15 分钟或未来超过 5 分钟标为 stale。
- LTA 时间标记为 collection_time_proxy，因为该接口没有规范化拍摄时间字段。
- JPEG 首尾标记检查用于排除错误页和部分截断；后续分析仍需完整解码及画质检查。
- 图片、日志、密钥均被 Git 忽略；LTA 签名 URL 查询参数不会写入归档。

车辆识别时按相应 images 根目录读取，优先用 manifest 的 `captured_at_sgt` 关联时间。
需要按车道方向新标 ROI，避免混合相反方向和高架遮挡。路段分组不等于可以直接
对所有摄像头多数投票。保留缺帧，不无限前向填充；后续先按时间划分数据，再生成
滑动窗口，避免训练/验证重叠造成信息泄漏。

## 验证与来源

```bash
python3 -m unittest discover -s tests -v
```

10 项测试覆盖八点三组配置、跨日、一周轮数、提前等待、10 分钟网格、结束时刻排除、
过期计划不请求、去重、缺帧、过期图、网络失败及链接脱敏。
2026-09-13 新八点本地试采全部成功；早期 Sentosa 两点验证见 `docs/verification.md`。

采集思路来自本地 `IND5003_GP17_Traffic-master`；原项目未被修改。
坐标来自旧项目目录并由实时接口核对；位置名称参考
[LTA API Guide Annex G](https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf)
和 [OneMotoring](https://onemotoring.lta.gov.sg/content/onemotoring/home/driving/traffic_information/traffic-cameras.html)。
数据归 LTA / 相应提供方所有，本仓库不为第三方图像另行授予许可。
