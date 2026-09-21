# 试采验证 · 2026-09-13

本机采集时间：2026-09-13 14:29:14 +08:00。
数据来源：`https://api.data.gov.sg/v1/transport/traffic-images`。
执行命令：`python3 scripts/fetch_lta_camera_images.py --once`，退出码 0。

| 摄像头 | 图像源时间（新加坡） | 结果 | 字节数 | SHA256 |
|---|---|---|---|---|
| 4798 | 2026-09-13 14:25:49 +08:00 | downloaded | 170526 | 23fba534c29f3f26a393867d0c7b1eabc078c06fc57eb839da39a10989d936ac |
| 4799 | 2026-09-13 14:25:49 +08:00 | downloaded | 178920 | d5b3ddff76a57794519e4c3a2f7eb14a4babc8d62487f95fa707b3e4c7c36100 |

两张 JPEG 已实际打开检查：均显示真实道路、车辆与方向标识，非错误页。
4798 显示朝 Telok Blangah 的道路及高架遮挡；4799 同时显示进岛和出岛车道。
本报告只证明首轮可用，不代表已经完成一周采集或证明摄像头长期稳定。

源文件保存在本地 `data/lta_images/images/<camera-id>/`，被 Git 忽略。
同目录下的 `manifest.csv` 和 `metadata/` 保存原始核验信息。

`python3 -m unittest discover -s tests -v`：7 项测试通过。
LTA 带密钥路径仅经过模拟测试；本机未配置 LTA_API_KEY。

## GitHub 云端试采

- 仓库：`waiwai033/ISY5002-Traffic-DATAfetch`，默认分支 main。
- [运行 34743008577](https://github.com/waiwai033/ISY5002-Traffic-DATAfetch/actions/runs/34743008577)
  于 2026-09-13 成功完成，参数 `duration_minutes=0`。
- 生成附件 `sentosa-images-34743008577-1`，ZIP 大小 335251 字节。
- 附件已下载回本地 `data/github/34743008577/`；两台摄像头均为 downloaded，
  图片字节数与 SHA256 均与 manifest 一致。
- 未使用 AWS、未设置 API Key，未开启持续采集排程。

## 八摄像头版本与排程启用 · 2026-09-13

以上是初始 Sentosa 两点版本的历史记录。当前版本已扩展为 8 个摄像头、3 个路段组。

- 代码提交：`dfadd94`，已推送到 GitHub main。
- [八点云端试采 34757763680](https://github.com/waiwai033/ISY5002-Traffic-DATAfetch/actions/runs/34757763680)
  成功完成，执行耗时 14 秒。
- 8/8 图片均为 downloaded，源时间为 2026-09-13 20:40:23 +08:00。
- 附件已下载到本地 `data/github/34757763680/`；全部图片字节数与 SHA256 核对一致，
  原始 JPEG 合计 1,352,067 字节。
- 10 项自动化测试已通过，包括开始前等待、10 分钟采样时刻对齐和结束时刻排除。
- 已设置并读回确认 `COLLECTION_ENABLED=true`。
- 正式采集窗口：2026-09-14 00:00 至 2026-09-21 00:00（Asia/Singapore，结束时刻不含）。
- 每 10 分钟采集一轮；一周理论 1,008 轮、最多 8,064 张。
- 数据保存在每批 Actions artifact，保留 30 天；未配置 AWS。
- 启用记录不代表一周采集已完成。GitHub 调度可能延迟或出现缺口，实际数据以 manifest 为准。
