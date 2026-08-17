# ETK 精简版 — Emby 翻译服务

> **当前版本：v5.9**（2026-08-17）
> 部署地址：**http://<你的IP>:8080**

从 [hbq0405/emby-toolkit](https://github.com/hbq0405/emby-toolkit)（AGPL v3.0）裁剪：
**只保留 AI 翻译功能**（标题/简介/演员/角色中文化），剔除 115 整理、订阅、分享、前端框架、nginx、ffmpeg、PostgreSQL。

---

## 📍 部署信息（当前）

| 项目 | 值 |
|---|---|
| **服务地址** | **http://<你的IP>:8080** |
| **Webhook 地址** | **http://<你的IP>:8080/webhook/emby** |
| 容器 | etk-lite:1.0（restart: unless-stopped）|
| 数据目录 | /vol1/1000/Docker/etk-lite/config/（config.json + etk.db + etk.log）|
| 时区 | Asia/Shanghai（北京时间）|

---

## ✨ 功能

- 🌐 **Web UI**（http://<你的IP>:8080）：
  - ⚙️ **配置**：Emby 地址/账密（或 API Key）、AI 服务商/Key/模型、TMDB Key（可选）、无简介占位开关、测试连接按钮（Emby + AI）
  - 🧪 **试译**：输入任意文字 → 选模式（人名音译/快速/质量）→ 立即翻译看效果（不写 Emby）
  - 📥 **批量翻译**：全库电影/剧集翻译（分页扫描 + 分批处理 + 节流防 Emby 过载），可填条数限制
  - 🎭 **人物**：全库 Person 名翻译写回（扫描统计 + 待翻译数 + 强制全翻）
  - ⏰ **定时**：APScheduler 每天自动批量翻译（默认凌晨 4-6 点）
  - 📋 **失败记录**：failed_log 可查可清空重试 + 清空已处理（强制全库重翻）
  - 🔍 **条目预览**：输入条目 ID → 预览标题/简介翻译效果（不写回）
  - 📝 **提示词**：9 个提示词全中文标签，可编辑可恢复默认
  - 📊 **任务**：实时进度条（扫描 0-40% → 翻译 40-100%）、当前处理条目、停止按钮
  - 📜 **日志**：每 5 秒自动刷新 + 自动滚动（手动上翻不打扰），只显示应用日志（无访问日志刷屏）
- 🔄 **Webhook 实时翻译**：Emby 新片入库 → 自动翻译（见下方配置步骤）
- 📋 **任务队列**：排队、去重（同一条目不重复翻译）、超时、失败重试、防卡死、可停止
- 🎭 **演员汉化**：演员名 + "饰"角色名（cast/guest_stars，按 order 排序，最多 30 人）
- 🎬 **导演/主创**：crew 中 Director/Series Director + created_by 翻译
- 🀄 **豆瓣集成**：翻译前查豆瓣权威中文演员表（**对齐校验**：豆瓣演员英文名须与 Emby 演员匹配才采用，防止错配电影污染演员表）
- 🧑 **全库人物名翻译**：扫描 Emby 全部 Person → 非中文名批量翻译 → 官方 API 写回（GET→改→POST，无需插件）
- 🔒 **演员锁定**：白名单（只写回最终保留演员）+ Diff 比对（名同不写）+ 已处理记录跳过
- 💾 **防重复翻译**：processed_log 表记录已处理条目，批量任务默认跳过（省 AI 钱），可强制全翻
- 📝 **NFO 维护**：通过 Emby API 更新元数据（Name/Overview），Emby 自动落盘 NFO
- 🔔 **Emby 刷新**：翻译后自动 POST /Items/{id}/Refresh 通知 Emby 刷新
- 💾 **SQLite 缓存**：翻译缓存表（人名强制缓存），重复词条不重复调用 AI

---

## 🎯 Emby Webhook 配置（实时翻译新片）

Emby 需要装 **Webhook 插件**（Emby 后台 → 插件目录 → 搜索 "Webhook" 安装 → 重启 Emby）。

然后：**Emby 管理后台 → 高级 → Webhook → 添加 Webhook**：

1. **URL** 填：`http://<你的IP>:8080/webhook/emby`
2. **勾选事件**（本服务处理这些）：
   - ✅ **媒体库新增内容**（ItemAdded / Library.NewMediaItem）← 实时翻译新片，**必勾**
   - （可选）媒体库更新内容（ItemUpdated）——如也勾了会重复翻译，建议不勾
3. 保存后，**新增一部电影/剧集 → 自动翻译 → 写回 → Emby 刷新**

> 事件类型说明：服务端只处理 `ItemAdded` / `Library.NewMediaItem` / `item.added`，且只处理 **Movie / Series / Episode** 三种类型，其他事件自动忽略。

---

## 🚀 启动（本机开发/调试）

```bash
cd /vol1/@appdata/trim.hermes/workspace/etk-lite
export AI_API_KEY=sk-xxx
export ETK_DB_PATH=$PWD/etk.db ETK_CONFIG_FILE=$PWD/config.json ETK_LOG_FILE=$PWD/etk.log
./venv/bin/python app.py    # 默认 8080 端口
```

## 🐳 Docker 部署（131）

```bash
cd /vol1/1000/Docker/etk-lite
docker compose up -d --build
```

---

## 🔌 API

| 接口 | 方法 | 说明 |
|---|---|---|
| /api/config | GET/POST | 读取/保存配置 |
| /api/translate | POST | 翻译单个条目 {item_id} |
| /api/batch | POST | 批量翻译 {item_type: Movie/Series} |
| /api/tasks | GET | 任务队列状态 |
| /api/tasks/cancel | POST | 停止当前任务 |
| /api/ai/trytranslate | POST | 试译 {text, mode} |
| /api/item/preview | POST | 条目翻译预览 {item_id} |
| /api/logs | GET | 查看日志 |
| /webhook/emby | POST | Emby 入库事件（实时翻译）|

---

## ⚙️ 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| ETK_PORT | 8080 | 服务端口 |
| EMBY_URL | http://<你的Emby地址>:8096 | Emby 地址 |
| EMBY_USER / EMBY_PASS | 你的用户 / 你的密码 | Emby 登录 |
| EMBY_API_KEY | - | Emby API Key（可选，优先于账密）|
| AI_API_KEY | - | DeepSeek/OpenAI/硅基流动 key |
| AI_BASE_URL | https://api.deepseek.com/v1 | API 地址（硅基流动: https://api.siliconflow.cn/v1）|
| AI_MODEL | deepseek-chat | 模型 |
| AI_REQUEST_TIMEOUT | 120 | AI 请求超时（秒）|
| TMDB_API_KEY | - | TMDB Key（可选，简介缺失时补全）|
| ETK_DB_PATH | /config/etk.db | SQLite 缓存位置 |
| ETK_CONFIG_FILE | /config/config.json | 配置文件 |
| ETK_LOG_FILE | /config/etk.log | 日志文件 |
| TZ | Asia/Shanghai | 时区（北京时间）|

> 环境变量是**首次启动的初始值**；保存 UI 配置后以 config.json 为准（UI 改后立即生效，无需重启）。
