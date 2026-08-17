#!/usr/bin/env python3
"""
ETK 精简版 — Flask 服务
提供: Web UI + REST API + Emby webhook（实时翻译）
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

import config_manager
from task_queue import task_queue
from translate_service import get_service

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("etk-server")

# 同时写文件（供 /api/logs 读取；目录不存在时自动创建）
_log_file = os.environ.get("ETK_LOG_FILE", "/config/etk.log")
try:
    _log_dir = os.path.dirname(_log_file)
    if _log_dir and not os.path.exists(_log_dir):
        os.makedirs(_log_dir, exist_ok=True)
    _fh = logging.FileHandler(_log_file, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(_fh)
    logging.getLogger().addHandler(_fh)  # 全局 handler，所有模块日志都进文件
except Exception as e:
    logger.warning(f"日志文件不可用（仅 stdout）: {e}")

app = Flask(__name__)
CORS(app)

# 关闭 Werkzeug 访问日志（避免 UI 轮询刷屏，只留应用日志）
logging.getLogger("werkzeug").setLevel(logging.WARNING)

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>ETK 精简版 - Emby 翻译</title>
<style>
body{font-family:system-ui,sans-serif;background:#1a1d24;color:#e8e8e8;margin:0;padding:20px}
.card{background:#242833;border-radius:10px;padding:18px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.3)}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:0 0 12px;color:#8ab4f8}
label{display:block;margin:8px 0 4px;color:#aaa;font-size:13px}
input,select{width:100%;padding:8px;border:1px solid #3a4050;border-radius:6px;background:#1a1d24;color:#e8e8e8;box-sizing:border-box}
input[type=checkbox]{width:auto}
.btn{background:#3b82f6;color:#fff;border:none;padding:10px 18px;border-radius:6px;cursor:pointer;font-size:14px;margin:8px 6px 0 0}
.btn:hover{background:#2f6ad0}.btn.gray{background:#4a5162}.btn.red{background:#dc2626}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #333a4a}
.status{padding:2px 8px;border-radius:4px;font-size:12px}
.status.running{background:#1e40af}.status.success{background:#065f46}
.status.failed{background:#7f1d1d}.status.queued{background:#713f12}
.logbox{background:#0f1117;border-radius:6px;padding:10px;font-family:monospace;font-size:12px;max-height:300px;overflow-y:auto;white-space:pre-wrap}
a{color:#8ab4f8;text-decoration:none}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.tip{color:#888;font-size:12px;margin-top:4px}
.tabs{display:flex;gap:4px;margin:16px 0;border-bottom:1px solid #333a4a;flex-wrap:wrap}
.tab{padding:8px 18px;cursor:pointer;border-radius:8px 8px 0 0;background:#242833;color:#aaa;font-size:14px;border:1px solid transparent;border-bottom:none}
.tab:hover{color:#e8e8e8}
.tab.active{background:#3b82f6;color:#fff}
.tabpage{display:none}
.tabpage.active{display:block}
.btn.sm{padding:5px 10px;font-size:12px}
.modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.6);z-index:99;padding:40px 20px}
.modal-box{background:#242833;max-width:800px;margin:0 auto;border-radius:10px;padding:20px;max-height:80vh;overflow-y:auto}
.close{float:right;cursor:pointer;color:#888;font-size:20px}
textarea{width:100%;padding:8px;border:1px solid #3a4050;border-radius:6px;background:#1a1d24;color:#e8e8e8;box-sizing:border-box;font-family:monospace;font-size:12px;min-height:120px}
table td{max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
</style>
</head>
<body>
<h1>🎬 ETK 精简版 · Emby 翻译 <span class="tip">v5.9</span></h1>
<div class="tip">服务地址: <span id="server_addr"></span> ｜ webhook: <span id="webhook_addr"></span>/webhook/emby（Emby 后台 → Webhook 插件 → 勾选"媒体库新增内容"即可实时翻译新片）</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('tab-config')">⚙️ 配置</div>
  <div class="tab" onclick="showTab('tab-try')">🧪 试译</div>
  <div class="tab" onclick="showTab('tab-batch')">📥 批量翻译</div>
  <div class="tab" onclick="showTab('tab-persons')">🎭 人物</div>
  <div class="tab" onclick="showTab('tab-schedule')">⏰ 定时</div>
  <div class="tab" onclick="showTab('tab-failed')">📋 失败记录</div>
  <div class="tab" onclick="showTab('tab-item')">🔍 条目预览</div>
  <div class="tab" onclick="showTab('tab-prompts')">📝 提示词</div>
  <div class="tab" onclick="showTab('tab-tasks')">📊 任务</div>
  <div class="tab" onclick="showTab('tab-logs')">📜 日志</div>
</div>

<div id="tab-config" class="tabpage active">
  <div class="card">
    <h2>⚙️ Emby 配置</h2>
    <label>Emby 地址</label><input id="emby_url" placeholder="http://127.0.0.1:8096">
    <label>Emby API Key（可选，推荐。Emby 后台→高级→API Key 生成。填了优先用 Key，留空用账密）</label>
    <input id="emby_api_key" type="password" placeholder="留空则用下方账密登录">
    <label>Emby 用户 / 密码（API Key 留空时用）</label>
    <div style="display:flex;gap:8px">
      <input id="emby_user" placeholder="root" style="flex:1">
      <input id="emby_pass" type="password" placeholder="密码" style="flex:1">
    </div>
    <button class="btn gray" onclick="testEmby()">🧪 测试 Emby 连接</button>
    <span id="emby_test_msg" class="tip"></span>
  </div>
  <div class="card">
    <h2>🤖 AI 配置</h2>
    <label>AI 服务商</label>
    <select id="ai_provider">
      <option value="openai">OpenAI（及兼容服务：DeepSeek/硅基流动/Moonshot 等）</option>
      <option value="zhipuai">智谱AI (ZhipuAI)</option>
      <option value="gemini">Google Gemini</option>
    </select>
    <label>API Key</label><input id="ai_key" type="password" placeholder="输入 API Key">
    <label>API Base URL（硅基流动: https://api.siliconflow.cn/v1，DeepSeek: https://api.deepseek.com/v1）</label>
    <input id="ai_base" placeholder="https://api.deepseek.com/v1">
    <label>模型名称</label>
    <div style="display:flex;gap:8px">
      <input id="ai_model" placeholder="deepseek-chat" style="flex:1">
      <button class="btn sm" onclick="refreshModels()">🔄 拉取模型列表</button>
    </div>
    <div id="model_list" class="tip"></div>
    <label>翻译模式</label>
    <select id="ai_mode">
      <option value="quality">质量模式（推荐，带作品上下文）</option>
      <option value="fast">快速模式（批量人名/短词）</option>
      <option value="transliterate">音译模式（人名专用）</option>
    </select>
    <label>TMDB API Key（可选。作用：Emby 条目缺简介时，从 TMDB 拉英文简介补全再翻译。不填也能翻译，只是缺简介的片不补。免费注册: themoviedb.org → 设置 → API）</label>
    <input id="tmdb_api_key" type="password" placeholder="留空也可翻译（数据源=Emby 已有数据）">
    <div style="margin-top:8px">
      <label style="display:inline;margin-right:12px"><input type="checkbox" id="translate_title" checked> 翻译标题</label>
      <label style="display:inline;margin-right:12px"><input type="checkbox" id="translate_overview" checked> 翻译简介</label>
      <label style="display:inline;margin-right:12px"><input type="checkbox" id="translate_actor"> 翻译演员/角色</label>
      <label style="display:inline"><input type="checkbox" id="joke_fallback"> 无简介小笑话占位</label>
    </div>
    <button class="btn" onclick="saveConfig()">💾 保存配置</button>
    <button class="btn gray" onclick="testAI()">🧪 测试连接</button>
    <span id="cfg_msg" class="tip"></span>
  </div>

  <div class="card">
    <h2>📊 缓存统计 <button class="btn gray sm" onclick="loadStats()" style="float:right">🔄 刷新</button></h2>
    <div id="cache_stats" class="tip">加载中...</div>
  </div>
</div>

<div id="tab-try" class="tabpage">
  <div class="card">
    <h2>🧪 AI 试译（不写入 Emby，纯测试）</h2>
    <label>输入要翻译的文字（人名 / 标题 / 简介均可）</label>
    <textarea id="try_text" placeholder="例如: The Matrix 或 基努·里维斯 或一段英文简介" style="min-height:80px"></textarea>
    <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
      <select id="try_mode" style="max-width:220px">
        <option value="fast">快速模式（人名/短词）</option>
        <option value="transliterate">音译模式（人名中文化）</option>
        <option value="quality">质量模式（带上下文）</option>
      </select>
      <button class="btn" onclick="tryTranslate()">🚀 开始翻译</button>
      <button class="btn gray" onclick="trySample()">🎲 示例</button>
    </div>
    <div id="try_result" style="margin-top:12px;padding:12px;background:#1a1d24;border-radius:6px;min-height:60px" class="tip">
      输入文字后点"开始翻译"，结果会显示在这里。可用来验证 AI 配置是否正常、翻译效果如何。
    </div>
    <div class="tip" style="margin-top:8px">试译用当前保存的 AI 配置（或下方临时配置）。不会写回 Emby。</div>
    <label style="margin-top:10px">临时配置（可选，填了优先用，不填用已保存的）</label>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <input id="try_key" type="password" placeholder="API Key（留空用已保存）" style="flex:1;min-width:200px">
      <input id="try_base" placeholder="Base URL（留空用已保存）" style="flex:1;min-width:200px">
      <input id="try_model" placeholder="模型（留空用已保存）" style="flex:1;min-width:150px">
    </div>
  </div>
</div>

<div id="tab-batch" class="tabpage">
  <div class="card">
    <h2>📥 批量翻译</h2>
    <label>条数限制（留空=全库，填数字=只处理最近 N 条）</label>
    <input id="batch_limit" placeholder="留空=全库" style="max-width:200px">
    <div style="margin-top:8px">
      <button class="btn" onclick="startBatch('Movie', false)">🎬 翻译电影</button>
      <button class="btn" onclick="startBatch('Series', false)">📺 翻译剧集</button>
      <button class="btn red" onclick="startBatch('Movie', true)">🎬 强制重翻电影</button>
      <button class="btn red" onclick="startBatch('Series', true)">📺 强制重翻剧集</button>
    </div>
    <div class="tip">默认跳过已处理条目（省 AI 费用）；"强制重翻"忽略已处理记录全量重翻。处理过的条目下次自动跳过，不会重头开始。</div>
    <div id="batch_stats" class="tip"></div>
  </div>
</div>

<div id="tab-persons" class="tabpage">
  <div class="card">
    <h2>🎭 全库人物名翻译</h2>
    <button class="btn red" onclick="startPersons()">🎭 翻译全部人物</button>
    <button class="btn gray" onclick="scanPersons()">🔍 人物扫描统计</button>
    <div class="tip">扫描 Emby 全部演员/导演/客串 → 非中文名 AI 翻译 → 官方 API 写回（无需插件）</div>
    <div id="person_stats" class="tip"></div>
  </div>
</div>

<div id="tab-schedule" class="tabpage">
  <div class="card">
    <h2>⏰ 定时任务</h2>
    <label>电影翻译 cron（默认每天 4:00）</label><input id="sched_movie" placeholder="0 4 * * *">
    <label>剧集翻译 cron（默认每天 5:00）</label><input id="sched_series" placeholder="0 5 * * *">
    <label>人物翻译 cron（默认每周日 6:00，可留空关闭）</label><input id="sched_persons" placeholder="0 6 * * 0">
    <div style="margin-top:8px">
      <label style="display:inline;margin-right:12px"><input type="checkbox" id="sched_movie_en" checked> 电影</label>
      <label style="display:inline;margin-right:12px"><input type="checkbox" id="sched_series_en" checked> 剧集</label>
      <label style="display:inline"><input type="checkbox" id="sched_persons_en"> 人物</label>
    </div>
    <button class="btn" onclick="saveSchedule()">💾 保存定时任务</button>
    <span id="sched_msg" class="tip"></span>
    <div class="tip">cron 格式: 分 时 日 月 周（如 0 4 * * * = 每天凌晨4点）</div>
  </div>
</div>

<div id="tab-failed" class="tabpage">
  <div class="card">
    <h2>📋 失败记录</h2>
    <button class="btn gray" onclick="loadFailed()">🔄 刷新</button>
    <button class="btn red sm" onclick="resetFailed()">清空失败记录</button>
    <button class="btn red sm" onclick="resetProcessed()">清空已处理（强制全库重翻）</button>
    <div id="failed_list" class="tip">加载中...</div>
  </div>
</div>

<div id="tab-item" class="tabpage">
  <div class="card">
    <h2>🔍 条目翻译预览（不写回，先看效果）</h2>
    <label>Emby 条目 ID（Emby 网页地址栏 /Items 后的数字，或任务结果里的 id）</label>
    <div style="display:flex;gap:8px">
      <input id="item_id_input" placeholder="例如 3172290" style="flex:1">
      <button class="btn" onclick="previewItem()">🔍 预览翻译</button>
    </div>
    <div id="item_preview_result" style="margin-top:12px;padding:12px;background:#1a1d24;border-radius:6px" class="tip">
      输入条目 ID 后点"预览翻译"，这里会显示该条目的标题/简介翻译效果（不会写入 Emby）。
    </div>
  </div>
</div>

<div id="tab-prompts" class="tabpage">
  <div class="card">
    <h2>📝 AI 提示词（可自定义）</h2>
    <div class="tip">修改后保存即生效。各提示词用途：<br>
      <b>人名快速翻译</b>=批量人名/短词<br>
      <b>人名音译</b>=人名中文化（音译）<br>
      <b>质量翻译</b>=带作品上下文的人名+角色名翻译<br>
      <b>简介翻译（单条）</b>=单条简介翻译<br>
      <b>标题翻译（单条）</b>=单条标题翻译<br>
      <b>文件名解析</b>=从文件名提取片名/年份/类型<br>
      <b>简介翻译（批量）</b>=批量简介翻译<br>
      <b>标题翻译（批量）</b>=批量标题翻译<br>
      <b>无简介占位</b>=简介缺失时让 AI 编个幽默简介占位（配合配置 Tab 的"无简介小笑话占位"开关）</div>
    <div id="prompt_editor">加载中...</div>
    <button class="btn" onclick="savePrompts()">💾 保存提示词</button>
    <button class="btn gray" onclick="resetPrompts()">↩️ 恢复默认</button>
    <span id="prompt_msg" class="tip"></span>
  </div>
</div>

<div id="tab-tasks" class="tabpage">
  <div class="card">
    <h2>📊 任务状态</h2>
    <div id="task_status">加载中...</div>
  </div>
</div>

<div id="tab-logs" class="tabpage">
  <div class="card">
    <h2>📜 日志（每 5 秒自动刷新）</h2>
    <button class="btn gray" onclick="loadLogs()">🔄 立即刷新</button>
    <div class="logbox" id="logbox">加载中...</div>
  </div>
</div>

<div id="promptModal" class="modal" onclick="if(event.target===this)this.style.display='none'">
  <div class="modal-box">
    <span class="close" onclick="document.getElementById('promptModal').style.display='none'">✕</span>
    <h2 id="promptModalTitle">编辑提示词</h2>
    <textarea id="promptModalText"></textarea>
    <button class="btn" onclick="savePromptModal()">💾 保存</button>
  </div>
</div>

<script>
let promptData = {};
function showTab(id) {
  document.querySelectorAll('.tabpage').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.querySelector(`.tab[onclick="showTab('${id}')"]`).classList.add('active');
  // 切到日志 Tab 时立即加载
  if (id === 'tab-logs') loadLogs();
  if (id === 'tab-failed') loadFailed();
  if (id === 'tab-prompts') loadPrompts();
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}
async function loadConfig() {
  const c = await api('/api/config');
  if (c && c.data) {
    document.getElementById('emby_url').value = c.data.emby_url || '';
    document.getElementById('emby_api_key').value = c.data.emby_api_key || '';
    document.getElementById('emby_user').value = c.data.emby_user || '';
    document.getElementById('emby_pass').value = c.data.emby_pass || '';
    document.getElementById('ai_provider').value = c.data.ai_provider || 'openai';
    document.getElementById('ai_key').value = c.data.ai_api_key || '';
    document.getElementById('ai_base').value = c.data.ai_base_url || '';
    document.getElementById('ai_model').value = c.data.ai_model_name || '';
    document.getElementById('ai_mode').value = c.data.ai_translation_mode || 'quality';
    document.getElementById('tmdb_api_key').value = c.data.tmdb_api_key || '';
    document.getElementById('translate_title').checked = !!c.data.ai_translate_title;
    document.getElementById('translate_overview').checked = !!c.data.ai_translate_overview;
    document.getElementById('translate_actor').checked = !!c.data.ai_translate_actor_role;
    document.getElementById('joke_fallback').checked = !!c.data.ai_joke_fallback;
  }
}
async function saveConfig() {
  const body = {
    emby_url: document.getElementById('emby_url').value,
    emby_api_key: document.getElementById('emby_api_key').value,
    emby_user: document.getElementById('emby_user').value,
    emby_pass: document.getElementById('emby_pass').value,
    ai_provider: document.getElementById('ai_provider').value,
    ai_api_key: document.getElementById('ai_key').value,
    ai_base_url: document.getElementById('ai_base').value,
    ai_model_name: document.getElementById('ai_model').value,
    ai_translation_mode: document.getElementById('ai_mode').value,
    tmdb_api_key: document.getElementById('tmdb_api_key').value,
    ai_translate_title: document.getElementById('translate_title').checked,
    ai_translate_overview: document.getElementById('translate_overview').checked,
    ai_translate_actor_role: document.getElementById('translate_actor').checked,
    ai_joke_fallback: document.getElementById('joke_fallback').checked,
  };
  const r = await api('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  document.getElementById('cfg_msg').textContent = r.success ? '✅ 已保存' : '❌ ' + (r.message || '失败');
  setTimeout(() => document.getElementById('cfg_msg').textContent = '', 3000);
}
async function refreshModels() {
  const key = document.getElementById('ai_key').value;
  if (!key) { document.getElementById('model_list').textContent = '⚠️ 请先填写 API Key'; return; }
  const r = await api('/api/ai/models');
  if (r.success && r.data && r.data.length) {
    const list = r.data.slice(0, 30).map(m => `<span style="display:inline-block;background:#1a1d24;padding:2px 8px;margin:2px;border-radius:4px;cursor:pointer" onclick="document.getElementById('ai_model').value='${m}'">${m}</span>`).join('');
    document.getElementById('model_list').innerHTML = `模型(${r.data.length}个，点击选用): ${list}`;
  } else {
    document.getElementById('model_list').textContent = '⚠️ 拉取失败（服务商可能不支持 /models 接口），请手动输入模型名';
  }
}
async function testAI() {
  document.getElementById('cfg_msg').textContent = '测试中...';
  const r = await api('/api/ai/test', {method:'POST'});
  document.getElementById('cfg_msg').textContent = (r.success ? '✅ ' : '❌ ') + (r.message || '');
  setTimeout(() => document.getElementById('cfg_msg').textContent = '', 5000);
}
async function testEmby() {
  // 先保存当前配置再测试（测试用表单里的最新值）
  document.getElementById('emby_test_msg').textContent = '测试中...';
  const r = await api('/api/emby/test', {method:'POST'});
  document.getElementById('emby_test_msg').textContent = (r.success ? '✅ ' : '❌ ') + (r.message || '');
  setTimeout(() => document.getElementById('emby_test_msg').textContent = '', 8000);
}
async function tryTranslate() {
  const text = document.getElementById('try_text').value.trim();
  if (!text) { alert('请输入要翻译的文字'); return; }
  const mode = document.getElementById('try_mode').value;
  const el = document.getElementById('try_result');
  el.textContent = '翻译中...';
  el.className = 'tip';
  // 临时配置（可留空）
  const cfg = {};
  const key = document.getElementById('try_key').value.trim();
  const base = document.getElementById('try_base').value.trim();
  const model = document.getElementById('try_model').value.trim();
  if (key) cfg.ai_api_key = key;
  if (base) cfg.ai_base_url = base;
  if (model) cfg.ai_model_name = model;
  const body = {text, mode};
  if (Object.keys(cfg).length) body.config = cfg;
  try {
    const r = await api('/api/ai/trytranslate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    if (r.success) {
      el.innerHTML = `<span style="color:#4ade80">${r.message}</span><br><br>
        <b>原文:</b> ${r.original}<br>
        <b>译文:</b> <span style="color:#8ab4f8;font-size:16px">${r.result || ''}</span><br>
        <span class="tip">模式: ${r.mode}</span>`;
      el.className = '';
    } else {
      el.innerHTML = `<span style="color:#f87171">❌ ${r.message || '翻译失败'}</span>`;
      el.className = '';
    }
  } catch(e) {
    el.innerHTML = `<span style="color:#f87171">❌ 请求失败: ${e.message || e}</span>`;
    el.className = '';
  }
}
function trySample() {
  const samples = ['The Matrix', 'Keanu Reeves', 'Interstellar', 'John Wick', 'Inception', 'Tom Hanks'];
  const pick = samples[Math.floor(Math.random() * samples.length)];
  document.getElementById('try_text').value = pick;
  tryTranslate();
}
async function startBatch(type, force) {
  const label = (type==='Movie'?'电影':'剧集') + (force ? '（强制重翻）' : '');
  const limitInput = document.getElementById('batch_limit').value.trim();
  const limit = limitInput ? parseInt(limitInput) || 0 : 0;
  if (!confirm('开始批量翻译' + label + '？' + (force ? '将忽略已处理记录全量重翻。' : '将跳过已翻译的条目。') + (limit ? `（限 ${limit} 条）` : '（全库）'))) return;
  const r = await api('/api/batch', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({item_type: type, force: !!force, limit: limit})});
  alert(r.message || (r.success ? '任务已提交' : '失败'));
  refreshTasks();
}
async function saveSchedule() {
  const body = {
    movie_cron: document.getElementById('sched_movie').value || '0 4 * * *',
    series_cron: document.getElementById('sched_series').value || '0 5 * * *',
    persons_cron: document.getElementById('sched_persons').value || '',
    movie_enabled: document.getElementById('sched_movie_en').checked,
    series_enabled: document.getElementById('sched_series_en').checked,
    persons_enabled: document.getElementById('sched_persons_en').checked,
  };
  const r = await api('/api/schedule', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  document.getElementById('sched_msg').textContent = r.success ? '✅ ' + r.message : '❌ ' + (r.message || '失败');
  setTimeout(() => document.getElementById('sched_msg').textContent = '', 4000);
}
async function loadSchedule() {
  const r = await api('/api/schedule');
  if (r.success && r.data) {
    const d = r.data;
    document.getElementById('sched_movie').value = d.movie_cron || '0 4 * * *';
    document.getElementById('sched_series').value = d.series_cron || '0 5 * * *';
    document.getElementById('sched_persons').value = d.persons_cron || '';
    document.getElementById('sched_movie_en').checked = d.movie_enabled !== false;
    document.getElementById('sched_series_en').checked = d.series_enabled !== false;
    document.getElementById('sched_persons_en').checked = !!d.persons_enabled;
  }
}
async function loadStats() {
  const r = await api('/api/stats');
  const el = document.getElementById('cache_stats');
  if (!r.success || !r.data) { el.textContent = '加载失败'; return; }
  const d = r.data;
  const dbSize = r.db_size ? (r.db_size / 1024).toFixed(1) + ' KB' : '未知';
  const names = {
    translation_cache: '翻译缓存（人员/标题/简介）',
    media_metadata: '媒体元数据',
    processed_log: '已处理记录（防重复翻译）',
    failed_log: '失败记录',
    app_settings: '配置项',
  };
  let html = `<p>数据库大小: <b>${dbSize}</b></p><table><tr><th>类型</th><th>数量</th></tr>`;
  for (const k of Object.keys(names)) {
    html += `<tr><td>${names[k]}</td><td><b>${d[k] ?? 0}</b> 条</td></tr>`;
  }
  html += '</table>';
  el.innerHTML = html;
}
async function loadFailed() {
  const r = await api('/api/records');
  const el = document.getElementById('failed_list');
  if (!r.success) { el.textContent = '加载失败'; return; }
  const failed = (r.data && r.data.failed) || [];
  if (!failed.length) { el.innerHTML = '✅ 无失败记录'; return; }
  let html = '<table><tr><th>ID</th><th>名称</th><th>类型</th><th>原因</th><th>错误</th><th>时间</th></tr>';
  failed.forEach(f => {
    html += `<tr><td>${f.item_id}</td><td>${f.item_name || ''}</td><td>${f.item_type || ''}</td><td>${f.reason || ''}</td><td title="${(f.error_message||'').replace(/"/g,'&quot;')}">${String(f.error_message||'').slice(0,40)}</td><td>${f.failed_at || ''}</td></tr>`;
  });
  html += '</table>';
  el.innerHTML = html;
}
async function resetFailed() {
  if (!confirm('清空全部失败记录？')) return;
  const r = await api('/api/records/reset', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({which:'failed'})});
  alert(r.message || '完成');
  loadFailed();
}
async function resetProcessed() {
  if (!confirm('清空"已处理"记录？下次批量翻译将全库重新翻译（会再次消耗 AI 费用）！')) return;
  const r = await api('/api/records/reset', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({which:'processed'})});
  alert(r.message || '完成');
}
async function loadPrompts() {
  const r = await api('/api/ai/prompts');
  if (!r.success || !r.data) return;
  promptData = r.data;
  const PROMPT_NAMES = {
    fast_mode: '人名快速翻译',
    transliterate_mode: '人名音译（中文化）',
    quality_mode: '质量翻译（人名+角色）',
    overview_translation: '简介翻译（单条）',
    title_translation: '标题翻译（单条）',
    filename_parsing: '文件名解析',
    batch_overview_translation: '简介翻译（批量）',
    batch_title_translation: '标题翻译（批量）',
    batch_joke_fallback: '无简介占位（老六笑话）',
  };
  const el = document.getElementById('prompt_editor');
  let html = '<table><tr><th>提示词</th><th>用途</th><th>操作</th></tr>';
  Object.keys(promptData).forEach(k => {
    const v = promptData[k] || '';
    const name = PROMPT_NAMES[k] || k;
    const preview = String(v).slice(0, 40) + (v.length > 40 ? '...' : '');
    html += `<tr><td><b>${name}</b><br><span class="tip">${k}</span></td><td>${preview}</td><td><button class="btn sm" onclick="openPromptModal('${k}')">✏️ 编辑</button></td></tr>`;
  });
  html += '</table>';
  el.innerHTML = html;
}
let editingPromptKey = '';
async function previewItem() {
  const iid = document.getElementById('item_id_input').value.trim();
  if (!iid) { alert('请输入条目 ID'); return; }
  const el = document.getElementById('item_preview_result');
  el.textContent = '预览中...';
  el.className = 'tip';
  try {
    const r = await api('/api/item/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({item_id: iid})});
    if (!r.success) {
      el.innerHTML = `<span style="color:#f87171">❌ ${r.message || '预览失败'}</span>`;
      el.className = '';
      return;
    }
    const d = r.data;
    let html = `<b>${d.name}</b> <span class="tip">(${d.type} · ID ${d.item_id})</span><br><br>`;
    // 标题
    html += `<b>标题：</b>${d.title_original}`;
    if (d.title_translated && d.title_translated !== d.title_original) {
      html += ` → <span style="color:#8ab4f8;font-size:16px">${d.title_translated}</span>`;
    } else {
      html += ` <span class="tip">（无需翻译或翻译失败）</span>`;
    }
    html += '<br><br>';
    // 简介
    html += `<b>简介（前200字）：</b>${d.overview_original || '(空)'}<br>`;
    if (d.overview_translated) {
      html += `<b>译文：</b><span style="color:#8ab4f8">${d.overview_translated}</span>`;
    } else {
      html += `<span class="tip">（简介无需翻译或翻译失败）</span>`;
    }
    html += '<br><br>';
    // 演员
    if (d.actors_original && d.actors_original.length) {
      html += `<b>演员（前5）：</b>${d.actors_original.join('、')}`;
    }
    el.innerHTML = html;
    el.className = '';
  } catch(e) {
    el.innerHTML = `<span style="color:#f87171">❌ 请求失败: ${e.message || e}</span>`;
    el.className = '';
  }
}
function openPromptModal(key) {
  editingPromptKey = key;
  document.getElementById('promptModalTitle').textContent = '编辑提示词: ' + key;
  document.getElementById('promptModalText').value = promptData[key] || '';
  document.getElementById('promptModal').style.display = 'block';
}
async function savePromptModal() {
  const newText = document.getElementById('promptModalText').value;
  const prompts = {}; prompts[editingPromptKey] = newText;
  const r = await api('/api/ai/prompts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({prompts})});
  document.getElementById('prompt_msg').textContent = r.success ? '✅ 已保存' : '❌ 失败';
  document.getElementById('promptModal').style.display = 'none';
  setTimeout(() => document.getElementById('prompt_msg').textContent = '', 3000);
  loadPrompts();
}
async function savePrompts() {
  const r = await api('/api/ai/prompts', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({prompts: promptData})});
  document.getElementById('prompt_msg').textContent = r.success ? '✅ 已保存全部提示词' : '❌ 失败';
  setTimeout(() => document.getElementById('prompt_msg').textContent = '', 3000);
}
async function resetPrompts() {
  if (!confirm('恢复全部默认提示词？自定义修改将丢失。')) return;
  const r = await api('/api/ai/prompts/reset', {method:'POST'});
  alert(r.message || '完成');
  loadPrompts();
}
async function startPersons() {
  if (!confirm('开始全库人物名翻译？将扫描所有演员/导演名，翻译非中文名并写回 Emby。\\n（人物多时耗时较长，后台排队执行）')) return;
  const r = await api('/api/persons', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({})});
  alert(r.message || (r.success ? '任务已提交' : '失败'));
  refreshTasks();
}
async function scanPersons() {
  document.getElementById('person_stats').textContent = '扫描中...';
  const r = await api('/api/persons/scan?limit=5000');
  if (r.success && r.data) {
    const total = r.data.total_persons || r.data.scanned;
    const remain = Math.max(0, r.data.need_translate || 0);
    let msg = `👥 人物统计: 扫描 ${r.data.scanned} / 全库 ${total} 人`;
    msg += ` | 已是中文 ${r.data.skipped_cn}`;
    msg += ` | 🔴 还有 ${remain} 个名字待翻译`;
    if (r.data.samples && r.data.samples.length) {
      msg += `\n示例: ${r.data.samples.slice(0, 5).join('、')}${r.data.samples.length > 5 ? '...' : ''}`;
    }
    document.getElementById('person_stats').textContent = msg;
  } else {
    document.getElementById('person_stats').textContent = '扫描失败';
  }
}
async function refreshTasks() {
  const d = await api('/api/tasks');
  if (!d.data) return;
  const el = document.getElementById('task_status');
  let html = '';
  if (d.data.current) {
    const c = d.data.current;
    const pct = c.progress || 0;
    const statusCls = c.status === 'running' ? 'running' : (c.status === 'failed' ? 'failed' : '');
    html += `<p>▶ 当前任务: <b>${c.name}</b> <span class="status ${statusCls}">${c.status === 'cancelled' ? '已停止' : c.status}</span></p>`;
    html += `<div style="background:#1a1d24;border-radius:6px;height:18px;margin:8px 0;overflow:hidden">
      <div style="background:#3b82f6;height:100%;width:${pct}%;transition:width .5s;display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff">${pct}%</div></div>`;
    if (c.progress_text) html += `<p class="tip">${c.progress_text}</p>`;
    if (c.total && c.done) html += `<p class="tip">进度: ${c.done}/${c.total}</p>`;
    if (c.status === 'running' || c.status === 'queued') {
      html += `<button class="btn red sm" onclick="cancelTask('${c.id}')">⏹ 停止任务</button>`;
    }
    if (c.error) html += `<p class="tip" style="color:#f87171">错误: ${String(c.error).slice(0,100)}</p>`;
  } else {
    html += '<p>空闲中</p>';
  }
  const tasks = (d.data.tasks || []).slice().reverse();
  if (tasks.length) {
    html += '<table style="margin-top:10px"><tr><th>状态</th><th>任务</th><th>时间</th><th>结果</th></tr>';
    tasks.slice(0, 10).forEach(t => {
      const cls = t.status === 'success' ? 'success' : (t.status === 'failed' ? 'failed' : (t.status === 'running' ? 'running' : 'queued'));
      let res = '';
      if (t.status === 'success' && t.result) {
        const r = typeof t.result === 'string' ? t.result : JSON.stringify(t.result);
        res = String(r).slice(0, 60);
      } else if (t.status === 'failed') {
        res = String(t.error || '失败').slice(0, 60);
      } else if (t.status === 'running') {
        res = (t.progress || 0) + '% ' + (t.progress_text || '');
      } else if (t.status === 'cancelled') {
        res = '已停止';
      }
      html += `<tr><td><span class="status ${cls}">${t.status === 'cancelled' ? '已停止' : t.status}</span></td><td>${t.name}</td><td>${new Date(t.created_at*1000).toLocaleTimeString()}</td><td>${res}</td></tr>`;
    });
    html += '</table>';
  }
  el.innerHTML = html;
}
async function cancelTask(taskId) {
  if (!confirm('停止当前任务？已处理的保留，未处理的跳过。')) return;
  const r = await api('/api/tasks/cancel', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({task_id: taskId})});
  alert(r.message || '完成');
  refreshTasks();
}
let logUserScrolled = false;
async function loadLogs() {
  const d = await api('/api/logs');
  const box = document.getElementById('logbox');
  if (document.getElementById('tab-logs').classList.contains('active')) {
    // 记录用户是否手动上翻（上翻则不再自动滚动）
    if (box.scrollTop + box.clientHeight < box.scrollHeight - 50) logUserScrolled = true;
    box.textContent = (d.data || '无日志').slice(-6000);
    if (!logUserScrolled) box.scrollTop = box.scrollHeight;
  }
}
setInterval(refreshTasks, 5000);
setInterval(loadLogs, 5000);  // 日志每 5 秒自动刷新

// 动态显示服务地址（不硬编码 IP，部署后自动正确）
(function() {
  const host = window.location.host;
  const base = 'http://' + host;
  document.getElementById('server_addr').textContent = base;
  document.getElementById('webhook_addr').textContent = base;
})();

loadConfig(); loadStats(); refreshTasks(); loadLogs(); loadSchedule(); loadFailed(); loadPrompts();
</script>
</body>
</html>
"""


# ---------- 页面 ----------
@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


# ---------- 配置 ----------
@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = config_manager.APP_CONFIG
    return jsonify({"success": True, "data": {
        "emby_url": cfg.get("emby_url", ""),
        "emby_api_key": cfg.get("emby_api_key", ""),
        "emby_user": os.environ.get("EMBY_USER", "root"),
        "emby_pass": os.environ.get("EMBY_PASS", ""),
        "ai_provider": cfg.get("ai_provider", "openai"),
        "ai_api_key": cfg.get("ai_api_key", ""),
        "ai_base_url": cfg.get("ai_base_url", ""),
        "ai_model_name": cfg.get("ai_model_name", ""),
        "ai_translation_mode": cfg.get("ai_translation_mode", "quality"),
        "tmdb_api_key": cfg.get("tmdb_api_key", ""),
        "ai_joke_fallback": cfg.get("ai_joke_fallback", False),
        "ai_translate_title": cfg.get("ai_translate_title", True),
        "ai_translate_overview": cfg.get("ai_translate_overview", True),
        "ai_translate_actor_role": cfg.get("ai_translate_actor_role", False),
    }})


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.get_json(silent=True) or {}
    cfg = config_manager.APP_CONFIG
    for key in ("emby_url", "emby_api_key", "emby_user", "emby_pass", "ai_provider",
                "ai_api_key", "ai_base_url", "ai_model_name", "ai_translation_mode",
                "tmdb_api_key", "ai_joke_fallback",
                "ai_translate_title", "ai_translate_overview", "ai_translate_actor_role"):
        if key in data and data[key] not in (None, ""):
            cfg[key] = data[key]
    # 持久化
    try:
        cfg_file = os.environ.get("ETK_CONFIG_FILE", "/config/config.json")
        os.makedirs(os.path.dirname(cfg_file), exist_ok=True)
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")

    # 配置已变：重建全局 service（让 AI/Emby client 用新配置重新初始化）
    try:
        from translate_service import reset_service
        reset_service()
    except Exception as e:
        logger.warning(f"重建 service 失败: {e}")
    return jsonify({"success": True, "message": "配置已保存"})


# ---------- 条目翻译预览（不写回，先看效果） ----------
@app.route("/api/item/preview", methods=["POST"])
def item_preview():
    """输入条目 ID → 预览翻译结果（标题/简介/演员将变成什么），不写回"""
    data = request.get_json(silent=True) or {}
    item_id = str(data.get("item_id") or "").strip()
    if not item_id:
        return jsonify({"success": False, "message": "请输入条目 ID"}), 400
    service = get_service()
    try:
        item = service.emby.get_item(item_id)
        if not item:
            return jsonify({"success": False, "message": f"条目 {item_id} 不存在"})
        # 构造翻译数据（不写回，只看结果）
        tdata = service._build_tmdb_data(item)
        preview = {
            "item_id": item_id,
            "name": item.get("Name", ""),
            "type": item.get("Type", ""),
            "title_original": tdata.get("title", ""),
            "overview_original": (tdata.get("overview") or "")[:200],
            "actors_original": [a.get("name", "") for a in (tdata.get("cast") or [])[:5]],
        }
        # 用试译 API 逻辑翻译标题（看效果）
        ai = service.ai
        title_result = {}
        try:
            title_result = ai.batch_translate([preview["title_original"]], mode="fast") if preview["title_original"] else {}
        except Exception:
            pass
        preview["title_translated"] = title_result.get(preview["title_original"], "")
        # 简介翻译（quality 模式，Qwen 不稳时跳过）
        preview["overview_translated"] = ""
        if preview["overview_original"] and len(preview["overview_original"]) > 10:
            try:
                ov = ai.batch_translate([preview["overview_original"]], mode="fast")
                preview["overview_translated"] = ov.get(preview["overview_original"], "")
            except Exception:
                pass
        return jsonify({"success": True, "data": preview})
    except Exception as e:
        return jsonify({"success": False, "message": f"预览失败: {str(e)[:120]}"})


# ---------- 批量翻译 ----------
@app.route("/api/batch", methods=["POST"])
def batch_translate():
    data = request.get_json(silent=True) or {}
    item_type = data.get("item_type", "Movie")
    limit = int(data.get("limit", 0))  # 0 = 全库
    refresh = data.get("refresh", True)
    force = data.get("force", False)
    service = get_service()

    task_id = task_queue.submit(
        f"批量翻译{item_type}{'(强制)' if force else ''}",
        service.batch_translate,
        item_type, limit, refresh, None, True, force,
        dedup_key=f"batch:{item_type}",
        timeout=3600, retries=0,
    )
    if task_id:
        return jsonify({"success": True, "message": f"批量翻译 {item_type} 已提交", "task_id": task_id})
    return jsonify({"success": False, "message": "任务已在队列中或提交失败"})


# ---------- 已处理/失败记录管理 ----------
@app.route("/api/records", methods=["GET"])
def records():
    from database import media_db
    failed = media_db.get_failed_list(50)
    return jsonify({"success": True, "data": {"failed": failed}})


@app.route("/api/records/reset", methods=["POST"])
def records_reset():
    """清空已处理记录（下次全库重新翻译）或失败记录"""
    from database import media_db
    data = request.get_json(silent=True) or {}
    which = data.get("which", "processed")
    if which == "processed":
        n = media_db.clear_processed()
        return jsonify({"success": True, "message": f"已清空 {n} 条已处理记录（下次将全库重翻）"})
    n = media_db.clear_failed()
    return jsonify({"success": True, "message": f"已清空 {n} 条失败记录"})


# ---------- 全库人物名翻译（演员/导演汉化写回 Emby） ----------
@app.route("/api/persons", methods=["POST"])
def translate_persons():
    data = request.get_json(silent=True) or {}
    limit = int(data.get("limit", 0))
    service = get_service()
    task_id = task_queue.submit(
        "全库人物名翻译",
        service.translate_all_persons,
        limit, None,
        dedup_key="persons:all",
        timeout=7200, retries=0,
    )
    if task_id:
        return jsonify({"success": True, "message": "全库人物名翻译已提交（后台执行）", "task_id": task_id})
    return jsonify({"success": False, "message": "人物翻译任务已在队列中"})


@app.route("/api/persons/scan", methods=["GET"])
def scan_persons():
    """快速采样扫描统计（只读前 N 人估算，不翻译不写回）"""
    service = get_service()
    result = {"scanned": 0, "need_translate": 0, "skipped_cn": 0, "samples": []}
    sample_limit = int(request.args.get("limit", 2000))
    persons, total = service.emby.get_persons(0, sample_limit)
    need_names = {}
    for p in persons or []:
        result["scanned"] += 1
        name = p.get("Name") or ""
        if not name:
            continue
        if service._has_cn(name):
            result["skipped_cn"] += 1
        else:
            need_names.setdefault(name, 0)
    result["total_persons"] = total
    result["need_translate"] = len(need_names)
    result["samples"] = list(need_names.keys())[:10]
    return jsonify({"success": True, "data": result})


# ---------- 单条翻译（手动/测试） ----------
@app.route("/api/translate", methods=["POST"])
def translate_one():
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    if not item_id:
        return jsonify({"success": False, "message": "缺少 item_id"}), 400
    service = get_service()
    result = service.translate_item(str(item_id), refresh=True)
    return jsonify({"success": result.get("changed", False),
                    "data": result})


# ---------- 任务状态 ----------
@app.route("/api/tasks", methods=["GET"])
def tasks_status():
    return jsonify({"success": True, "data": task_queue.get_status()})


@app.route("/api/tasks/cancel", methods=["POST"])
def tasks_cancel():
    """停止当前/指定任务"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")
    ok = task_queue.cancel(task_id)
    return jsonify({"success": ok, "message": "已请求停止任务" if ok else "无运行中任务"})


# ---------- 日志 ----------
@app.route("/api/logs", methods=["GET"])
def logs():
    log_file = os.environ.get("ETK_LOG_FILE", "/config/etk.log")
    try:
        with open(log_file, encoding="utf-8", errors="replace") as f:
            content = f.read()
        return jsonify({"success": True, "data": content[-8000:]})
    except Exception:
        return jsonify({"success": True, "data": "(无日志文件)"})


# ---------- 定时任务 ----------
@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    from database import settings_db
    cfg = settings_db.get_setting("scheduled_tasks") or {}
    return jsonify({"success": True, "data": cfg})


@app.route("/api/schedule", methods=["POST"])
def set_schedule():
    from database import settings_db
    from scheduler import setup_scheduled_jobs
    data = request.get_json(silent=True) or {}
    allowed = {"movie_cron", "series_cron", "persons_cron",
               "movie_enabled", "series_enabled", "persons_enabled"}
    cfg = settings_db.get_setting("scheduled_tasks") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    for k, v in data.items():
        if k in allowed and v is not None:
            if isinstance(v, bool):
                cfg[k] = bool(v)
            else:
                cfg[k] = str(v)
    settings_db.save_setting("scheduled_tasks", cfg)
    try:
        setup_scheduled_jobs()
        return jsonify({"success": True, "message": "定时任务已更新", "data": cfg})
    except Exception as e:
        logger.error(f"定时任务配置失败: {e}")
        return jsonify({"success": False, "message": f"配置失败: {e}"})


# ---------- AI 模型列表 + 测试 ----------
@app.route("/api/ai/models", methods=["GET"])
def ai_models():
    service = get_service()
    models = service.list_ai_models()
    return jsonify({"success": True, "data": models})


@app.route("/api/ai/test", methods=["POST"])
def ai_test():
    """测试 AI 连接（用一条简单翻译验证 key/base_url/model 可用）"""
    service = get_service()
    try:
        result = service.ai.batch_translate(["Test"], mode="fast")
        ok = bool(result) and "Test" in result and result["Test"]
        return jsonify({"success": ok, "message": "连接正常" if ok else "翻译返回异常",
                        "result": result.get("Test") if result else None})
    except Exception as e:
        return jsonify({"success": False, "message": f"连接失败: {str(e)[:100]}"})


@app.route("/api/ai/trytranslate", methods=["POST"])
def ai_try_translate():
    """试译：输入任意文本，按指定模式翻译，立即返回结果（不写 Emby）"""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "message": "请输入要翻译的文字"}), 400
    mode = data.get("mode", "quality")  # fast / quality / transliterate
    # 允许传临时配置（未保存的 key/base_url/model 也可试）
    temp_cfg = data.get("config") or {}
    service = get_service()
    try:
        ai = service.ai
        # 若有临时配置，用临时配置创建临时翻译器
        if temp_cfg:
            import config_manager as cm
            merged = dict(cm.APP_CONFIG)
            for k, v in temp_cfg.items():
                if v not in (None, ""):
                    merged[k] = v
            from ai_translator import AITranslator
            from ai_compat import wrap_client
            ai = AITranslator(merged)
            try:
                if ai.client is not None:
                    ai.client = wrap_client(ai.client)
            except Exception:
                pass
        # 按模式翻译
        if mode == "transliterate":
            result = ai.batch_translate([text], mode="transliterate")
        elif mode == "quality":
            result = ai.batch_translate([text], mode="quality")
        else:
            result = ai.batch_translate([text], mode="fast")
        translated = (result or {}).get(text, "")
        # 兜底：AI 返回结构不对（如 Qwen 把输入当 context 重生成）时，提取值里的中文
        if not translated and result:
            import re as _r
            for v in result.values():
                if isinstance(v, str) and _r.search(r'[\u4e00-\u9fff]', v):
                    translated = v
                    break
                if isinstance(v, (list, dict)):
                    vstr = str(v)
                    m = _r.search(r'[\u4e00-\u9fff]{2,}', vstr)
                    if m:
                        translated = m.group(0)
                        break
        if translated and translated != text:
            return jsonify({"success": True, "message": "✅ 翻译成功",
                            "original": text, "result": translated, "mode": mode})
        elif translated == text:
            return jsonify({"success": True, "message": "✅ 连接正常（AI 认为无需翻译，返回原词）",
                            "original": text, "result": translated, "mode": mode})
        return jsonify({"success": False,
                        "message": "翻译返回为空（fast/快速模式适合人名短词，标题/简介请用质量模式）",
                        "result": translated})
    except Exception as e:
        return jsonify({"success": False, "message": f"翻译失败: {str(e)[:150]}"})


@app.route("/api/emby/test", methods=["POST"])
def emby_test():
    """测试 Emby 连接（登录 + 拉一条数据验证）"""
    service = get_service()
    try:
        ok = service.emby.login()
        if not ok:
            return jsonify({"success": False, "message": "Emby 登录失败（地址/API Key/账密不对？）"})
        # 拉一条电影验证 API 可用
        items = service.emby.scan_items("Movie", limit=1)
        if items is None:
            return jsonify({"success": False, "message": "Emby 连接成功但查询失败（用户权限？）"})
        total = len(items)
        info = f"✅ Emby 连接正常（用户: {service.emby.username or 'API Key'}，可读取条目）"
        return jsonify({"success": True, "message": info, "sample": items[0].get("Name") if items else None})
    except Exception as e:
        return jsonify({"success": False, "message": f"Emby 测试失败: {str(e)[:100]}"})


# ---------- 缓存统计 ----------
@app.route("/api/stats", methods=["GET"])
def cache_stats():
    """缓存统计：各表行数 + 数据库文件大小"""
    import sqlite3
    db_path = os.environ.get("ETK_DB_PATH", "/config/etk.db")
    stats = {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        for t in ("translation_cache", "media_metadata", "processed_log",
                  "failed_log", "app_settings"):
            try:
                stats[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                stats[t] = 0
        conn.close()
    except Exception as e:
        stats["_error"] = str(e)
    db_size = 0
    try:
        db_size = os.path.getsize(db_path)
    except Exception:
        pass
    return jsonify({"success": True, "data": stats, "db_size": db_size})


# ---------- AI 提示词管理（用户可自定义，原版 /api/ai/prompts） ----------
@app.route("/api/ai/prompts", methods=["GET"])
def ai_prompts_get():
    from database import settings_db
    from utils import DEFAULT_AI_PROMPTS
    user_prompts = settings_db.get_setting("ai_user_prompts") or {}
    if not isinstance(user_prompts, dict):
        user_prompts = {}
    # 返回全部提示词（默认值 + 用户覆盖）
    merged = {k: user_prompts.get(k, v) for k, v in DEFAULT_AI_PROMPTS.items()}
    return jsonify({"success": True, "data": merged,
                    "custom_keys": list(user_prompts.keys())})


@app.route("/api/ai/prompts", methods=["POST"])
def ai_prompts_save():
    from database import settings_db
    data = request.get_json(silent=True) or {}
    prompts = data.get("prompts") or {}
    if not isinstance(prompts, dict):
        return jsonify({"success": False, "message": "格式错误"}), 400
    settings_db.save_setting("ai_user_prompts", prompts)
    return jsonify({"success": True, "message": "提示词已保存"})


@app.route("/api/ai/prompts/reset", methods=["POST"])
def ai_prompts_reset():
    from database import settings_db
    settings_db.delete_setting("ai_user_prompts")
    return jsonify({"success": True, "message": "已恢复默认提示词"})


# ---------- Webhook（Emby 入库实时翻译） ----------
@app.route("/webhook/emby", methods=["POST"])
def webhook_emby():
    data = request.get_json(silent=True) or {}
    logger.debug(f"收到 webhook: {json.dumps(data, ensure_ascii=False)[:300]}")
    service = get_service()
    result = service.handle_webhook(data)
    return jsonify({"status": "ok", **result})


if __name__ == "__main__":
    # 启动定时任务（失败不影响主服务）
    try:
        from scheduler import setup_scheduled_jobs
        setup_scheduled_jobs()
        logger.info("定时任务已注册")
    except Exception as e:
        logger.warning(f"定时任务注册失败（不影响主服务）: {e}")
    port = int(os.environ.get("ETK_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
