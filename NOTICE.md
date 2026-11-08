# NOTICE

**OfferSheep** 是 [offercontext/offerPilot](https://github.com/offercontext/offerPilot) 的个人二次开发版本。

- 上游项目：offercontext/offerPilot，基线提交 `9f31f979`（2026-11-06）
- 许可证：沿用上游 **GNU AGPL-3.0**（见 [LICENSE](LICENSE)）。本仓库的全部修改同样以 AGPL-3.0 发布；
  若以网络服务形式向他人提供修改后的版本，须按 AGPL 第 13 条向其用户提供对应源代码。
- 上游版权归 offercontext 及其贡献者所有；OfferSheep 的修改由本仓库作者完成。

## 主要修改（2026-11）

1. **面试录音转写与 AI 复盘**：上传面试录音（MP3/M4A/WAV/WebM，≤500 MiB），经 OpenAI 兼容
   `/audio/transcriptions` 接口（默认硅基流动 SenseVoiceSmall）转写；有 ffmpeg 时按 10 分钟分片处理长录音；
   转写稿经大模型生成复盘草稿（总结、问题清单、表现反思、薄弱点），填入表单由用户确认后保存。
   DeepSeek 的 `response_format` 只支持 `text`/`json_object`（不支持 `json_schema`），因此官方 DeepSeek
   端点改用 Tool Calls 的 strict 模式（Beta 端点、强制工具调用、关闭思考模式）按 JSON Schema 约束输出，
   失败时回退通用 JSON 解析路径。
2. **设置 → 语音**：语音识别服务配置、密钥掩码显示与连接测试。
3. **形象替换**：移除上游的 Live2D 样例角色 Haru 及 Cubism/Pixi 运行时（Live2D Inc. 素材不属于 AGPL 授权），
   改为小羊「咩咩」——使用作者本人提供的插画（Canvas 2D 绘制，附原创矢量兜底形象）。
4. **品牌**：界面产品名改为 OfferSheep；内部 Python 包名 `offerpilot`、环境变量与本地存储键保持不变，便于同步上游。
5. **数据目录**：源码运行时默认保存在仓库同级目录 `offersheep-data/`（仍可用 `OFFERPILOT_DATA` 覆盖），
   数据库与密钥配置不进入仓库目录。
6. **Agent 可操作**：新增 `oc track` 命令组（JSON 输出）与 `skills/offersheep/SKILL.md`，
   便于 ZCode 等编码 Agent 代为记录投递、管理待办提醒、上传录音和生成复盘。
7. **流程完善**：投递详情页状态快捷切换；待办到点的桌面系统通知；面试结束后一键创建跟进提醒。
8. 上游若干依赖 offerPilot 提交历史的“历史门禁”测试，在缺少对应提交时自动跳过。

## 第三方素材

- 小羊「咩咩」插画：由本仓库作者提供（AI 辅助生成），随本仓库发布。
- 离线 Whisper 相关组件说明见 `web/public/offline-whisper-NOTICE.md`（Apache-2.0）。
