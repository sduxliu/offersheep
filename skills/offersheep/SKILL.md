---
name: offersheep
description: 用 OfferSheep 帮用户记录与跟踪求职：新增投递、更新投递状态、创建待办和提醒、登记面试、上传面试录音并转写、用 AI 生成面试复盘、导入求职邮件。当用户说“记一条投递”“我投了某公司”“更新投递状态”“加个待办/提醒”“约了面试”“上传面试录音”“帮我复盘这场面试”“今天有什么要跟进”“我收到一封面试邀请邮件”时使用。
---

# OfferSheep 求职记录操作手册

OfferSheep 是本地运行的求职记录工作台。你（Agent）通过 `oc track` 命令操作它，命令输出都是 JSON。不要直接改数据库文件，也不要读取或输出任何 API Key。

## 0. 确认服务在运行

在仓库根目录（含 `pyproject.toml` 的 offersheep 目录）执行：

```bash
curl -s http://127.0.0.1:8080/api/health
```

返回 `{"status":"ok"}` 即可。否则在后台启动：`uv run oc start`，等几秒再检查。界面地址是 http://localhost:8080 。

## 1. 命令速查

| 场景 | 命令 |
| --- | --- |
| 查看投递 | `uv run oc track apps [--status interview]` |
| 新增投递 | `uv run oc track add-app --company 公司 --position 岗位 [--url 链接] [--notes 渠道/内推人] [--status applied]` |
| 改投递状态 | `uv run oc track set-status <投递ID> <pending\|applied\|written_test\|interview\|offer\|closed> [--reason 关闭原因]` |
| 加待办+提醒 | `uv run oc track add-todo <投递ID> --title 标题 --due "2026-11-20 10:00" [--remind "2026-11-20 09:00"] [--type custom\|deadline]` |
| 登记面试 | `uv run oc track add-interview <投递ID> --at "2026-11-12 14:00" [--round 二面] [--location 会议链接]` |
| 看待办 | `uv run oc track todos [--app <投递ID>] [--pending]` |
| 完成待办/面试 | `uv run oc track done <日程ID>` |
| 今日提醒 | `uv run oc track reminders` |
| 导入求职邮件 | `uv run oc track mail-import <邮件文本文件> [--subject 主题] [--received "2026-11-08 10:00"]` |
| 查看邮件建议 | `uv run oc track mail-suggestions`（待审日程建议，需用户在界面「提醒」页核对后才写入） |
| 上传录音 | `uv run oc track upload <面试日程ID> <录音文件路径>` |
| 转写录音 | `uv run oc track transcribe <录音ID>`（默认等待完成） |
| 查看转写 | `uv run oc track recording <录音ID>` |
| AI 复盘草稿 | `uv run oc track review-draft <录音ID>`（只生成，不写入） |
| 保存复盘 | `uv run oc track review-draft <录音ID> --save` |

时间不带时区时按本机时区处理。状态含义：pending 待投递、applied 已投递、written_test 笔试、interview 面试中、offer 已拿 Offer、closed 已结束。

## 2. 常用流程

**投完简历**：`add-app` 记录（备注写渠道），再 `add-todo` 一条 7 天后的「跟进投递进度」。

**收到面试邀请**：`set-status <ID> interview`，再 `add-interview` 登记时间与会议链接（默认提前 1 天提醒）。
若用户给的是邮件文本（或让 AI 去 Boss/邮箱复制邀请内容），可先 `mail-import` 生成待审建议，
提醒用户到「提醒」页核对确认——不要替用户确认邮件建议。

**从 Boss 等平台投递后**：让 AI 先 `apps` 查重，再 `add-app` 记录（备注写渠道和 JD 链接），`add-todo` 一条 7 天后的「跟进投递进度」。

**面试结束后**：
1. `upload` 录音，`transcribe` 转写；
2. `review-draft` 生成草稿，把总结、问题清单、薄弱点用中文简要展示给用户；
3. 用户确认后才执行 `review-draft --save` 写入复盘；
4. `done <面试日程ID>`，再 `add-todo` 一条 3 天后的「跟进面试结果」。

**每天开始时**：`reminders` 和 `todos --pending`，按紧急程度整理给用户。

**拿到结果**：挂了用 `set-status <ID> closed --reason "一面未通过"`；拿到 Offer 用 `set-status <ID> offer`。

## 3. 规则

- `--save`、`set-status ... closed` 这类写入要先征得用户同意；新增投递/待办可以直接做并告知结果。
- 命令失败时读 stderr 里的 JSON：`status` 与 `detail.error_code` 说明原因。`asr_unconfigured` 表示需要用户在 设置 → 语音 中配置语音识别；连接失败说明服务没启动。
- 投递 ID、日程 ID、录音 ID 都从前一条命令的 JSON 输出里取，不要猜。
- 不要把录音转写稿、密钥或数据目录里的文件内容外发到其他服务。
