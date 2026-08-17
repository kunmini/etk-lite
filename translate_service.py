#!/usr/bin/env python3
"""
ETK 精简版 — 翻译服务
封装原版翻译引擎，提供:
  - translate_item_by_id: 按 Emby ID 翻译（webhook 实时翻译用）
  - batch_translate_all: 全库批量翻译（排队任务）
  - 翻译后自动写回 Emby + 通知刷新
"""
import logging
import re
import sys
import os
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__))

import config_manager
from ai_translator import AITranslator
from database import connection
from tasks.helpers import translate_tmdb_metadata_recursively
from emby_api import EmbyAPI
from handler.douban import DoubanApi
import utils


class TranslateService:
    def __init__(self):
        self.emby: Optional[EmbyAPI] = None
        self.ai: Optional[AITranslator] = None
        self.douban: Optional[DoubanApi] = None
        self._wait_idle_before_write = False
        self._ensure_clients()

    def _ensure_clients(self):
        cfg = config_manager.APP_CONFIG
        if self.emby is None:
            # 优先用 config.json 里的值（131 迁移过来的一致配置），env 只是兜底
            self.emby = EmbyAPI(cfg.get("emby_url") or os.environ.get("EMBY_URL", "http://127.0.0.1:8096"),
                                cfg.get("emby_user") or os.environ.get("EMBY_USER", "root"),
                                cfg.get("emby_pass") or os.environ.get("EMBY_PASS", "123"),
                                api_key=cfg.get("emby_api_key", ""))
            self.emby.login()
        if self.ai is None:
            from ai_compat import wrap_client
            self.ai = AITranslator(cfg)
            # 包装 client：json_object 失败自动降级（兼容 Ollama 等）
            try:
                if self.ai.client is not None:
                    self.ai.client = wrap_client(self.ai.client)
            except Exception as e:
                logger.debug(f"AI 兼容包装跳过: {e}")
        if self.douban is None:
            self.douban = DoubanApi(cooldown_seconds=1.5)

    def list_ai_models(self) -> list:
        """从 AI 服务商 models 接口拉模型列表（UI 下拉选择用）"""
        try:
            import requests as _r
            cfg = config_manager.APP_CONFIG
            base = (cfg.get("ai_base_url") or "https://api.deepseek.com/v1").rstrip("/")
            key = cfg.get("ai_api_key") or ""
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            resp = _r.get(f"{base}/models", headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data") or []
            return [m.get("id") for m in models if m.get("id")]
        except Exception as e:
            logger.error(f"拉取模型列表失败: {e}")
            return []

    def _translation_config(self) -> dict:
        cfg = config_manager.APP_CONFIG
        return {
            "ai_translate_title": cfg.get("ai_translate_title", True),
            "ai_translate_overview": cfg.get("ai_translate_overview", True),
            "ai_translate_episode_overview": cfg.get("ai_translate_episode_overview", True),
            "ai_translate_actor_role": cfg.get("ai_translate_actor_role", False),
            "ai_translation_mode": cfg.get("ai_translation_mode", "quality"),
            "remove_actors_without_avatars": False,
        }

    def _build_tmdb_data(self, item: dict) -> dict:
        people = item.get("People") or []
        return {
            "id": item.get("Id"),
            "title": item.get("Name"),
            "name": item.get("Name"),
            "overview": item.get("Overview"),
            "tagline": (item.get("Taglines") or [""])[0] if item.get("Taglines") else "",
            "release_date": str(item.get("ProductionYear") or ""),
            "credits": {
                "cast": [{"name": p.get("Name"), "character": p.get("Role"),
                          "emby_person_id": p.get("Id"), "person": p}
                         for p in people if p.get("Type") == "Actor"][:30],
                "crew": [{"name": p.get("Name"), "job": p.get("Type"),
                          "emby_person_id": p.get("Id"), "person": p}
                         for p in people if p.get("Type") in ("Director", "Writer")][:8],
            },
        }

    def _has_cn(self, text: str) -> bool:
        return bool(text) and bool(re.search(r'[\u4e00-\u9fff]', text or ""))

    def _has_cjk(self, text: str) -> bool:
        """检测是否含中日韩文字（中文汉字 + 日文假名 + 韩文谚文）。
        人物翻译用：已是东亚文字的名字（如韩文 오영미、日文假名）不再送 AI 翻译，
        避免 fast 模式把韩文/日文名乱译、浪费 token（只翻译拉丁字母等外文名）。"""
        if not text:
            return False
        return bool(re.search(
            r'[\u4e00-\u9fff\u3400-\u4dbf'          # 中文汉字（含扩展A）
            r'\u3040-\u30ff\u31f0-\u31ff'           # 日文平假名/片假名
            r'\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]',  # 韩文谚文
            text))

    def _fetch_douban_cast(self, item: dict) -> Optional[list]:
        """查豆瓣演员表（中文名+角色名），返回 TMDb 兼容 cast 列表或 None。
        用 IMDb ID + 片名 + 年份匹配豆瓣，拉取权威中文演员表。
        """
        if not config_manager.APP_CONFIG.get("douban_enable_online_api", True):
            return None
        try:
            name = item.get("Name") or ""
            imdb_id = (item.get("ProviderIds") or {}).get("Imdb")
            year = str(item.get("ProductionYear") or "")
            mtype = "tv" if item.get("Type") == "Series" else "movie"
            if not name:
                return None
            logger.info(f"[豆瓣] 匹配: {name} (IMDb: {imdb_id or '无'}, {year})")
            result = self.douban.get_acting(
                name=name, imdbid=imdb_id, mtype=mtype, year=year)
            cast = result.get("cast") or []
            if cast:
                logger.info(f"[豆瓣] 获取到 {len(cast)} 位演员 (豆瓣ID: {result.get('id', '?')})")
            return cast or None
        except Exception as e:
            logger.warning(f"[豆瓣] 查询失败: {e}")
            return None

    def _merge_douban_cast(self, data: dict, douban_cast: list):
        """把豆瓣中文演员表合并进翻译数据：
        - 豆瓣 cast 里已有中文名的演员，直接采用（不再 AI 翻译）
        - 用豆瓣的 order 覆盖排序
        - ★ 对齐校验：豆瓣演员的 original_name（英文名）须与 Emby/TMDb 演员匹配，
          否则丢弃（防止错配电影（如 The Moon→穿过月亮的旅行）污染演员表）
        """
        if not douban_cast:
            return
        credits = data.setdefault("credits", {})
        existing = credits.get("cast") or []
        # 建立 Emby/TMDb 已有演员的英文名索引（用于对齐校验）+ 英文名→演员映射（继承 emby_person_id）
        existing_en = set()
        existing_by_en = {}
        for a in existing:
            key = (a.get("name") or "").strip().lower()
            if key:
                existing_en.add(key)
                existing_by_en.setdefault(key, a)
            orig = (a.get("original_name") or "").strip().lower()
            if orig:
                existing_en.add(orig)
                existing_by_en.setdefault(orig, a)
        merged = []
        seen = set()
        for d_actor in douban_cast:
            d_name = d_actor.get("name") or ""
            if not d_name:
                continue
            # ★ 对齐校验：豆瓣演员英文名必须与已有演员匹配
            d_orig = (d_actor.get("original_name") or "").strip().lower()
            matched = existing_by_en.get(d_orig) if d_orig else None
            if d_orig and existing_en and d_orig not in existing_en:
                logger.debug(f"[豆瓣] 跳过不匹配演员: {d_name} (英文名 {d_orig} 不在现有演员中)")
                continue
            merged.append({
                "name": d_name,
                "character": d_actor.get("character") or "",
                "original_name": d_actor.get("original_name") or d_name,
                "order": d_actor.get("order", len(merged)),
                "profile_path": d_actor.get("profile_path"),
                # ★ 继承匹配到的 Emby 演员的 Person ID，供翻译后写回 People 精确匹配
                "emby_person_id": (matched or {}).get("emby_person_id"),
                "person": (matched or {}).get("person"),
            })
            seen.add(d_name.lower())
        # 补充未在豆瓣的 TMDb 演员（保留原有顺序）
        for a in existing:
            key = (a.get("name") or "").strip().lower()
            if key and key not in seen:
                merged.append(a)
                seen.add(key)
        credits["cast"] = merged[:30]

    def _build_people_writeback(self, item: dict, data: dict):
        """翻译后：把翻译好的演员名/角色名写回 Emby 的 People 字段。
        安全网（对齐原版 _update_emby_person_names）：
        - 只改翻译后【含中文】的名字/角色名（白名单，不覆盖用户手动改的）
        - 只改确实变化的（Diff）
        - 保留头像 PrimaryImageTag / PersonId / ProviderIds / order 等其他字段
        - 角色名清理"饰/配/as"前后缀（对齐原版 clean_character_name_static）
        返回新的 People 列表；无变化返回 None。
        """
        people = item.get("People") or []
        if not people:
            return None
        # person_id -> 翻译后项（cast=演员，crew=导演/编剧）
        trans_by_id = {}
        for grp in ("cast", "crew"):
            for a in (data.get("credits") or {}).get(grp) or []:
                pid = a.get("emby_person_id")
                if pid:
                    trans_by_id.setdefault(str(pid), a)
        if not trans_by_id:
            return None
        # 判断是否动画（角色名空时原版填"配音/演员"，此处暂不强填，仅清理前缀）
        changed = False
        new_people = []
        for p in people:
            t = trans_by_id.get(str(p.get("Id") or ""))
            if not t:
                new_people.append(p)
                continue
            np_ = dict(p)  # 浅拷贝，避免污染原 item
            # 演员/导演名：翻译后含中文才写
            new_name = (t.get("name") or "").strip()
            if new_name and self._has_cn(new_name) and new_name != p.get("Name"):
                np_["Name"] = new_name
                changed = True
            # 角色名（仅 Actor）：翻译后含中文才写，清理"饰/配/as"前后缀
            if p.get("Type") == "Actor":
                new_role = (t.get("character") or "").strip()
                if new_role:
                    new_role = utils.clean_character_name_static(new_role)
                if new_role and self._has_cn(new_role) and new_role != p.get("Role"):
                    np_["Role"] = new_role
                    changed = True
            new_people.append(np_)
        return new_people if changed else None

    def needs_translation(self, item: dict) -> bool:
        name = item.get("Name") or ""
        overview = item.get("Overview") or ""
        return (bool(name) and not self._has_cn(name)) or (bool(overview) and not self._has_cn(overview))

    # ---------- 单条翻译（webhook 实时） ----------
    def translate_item(self, item_id: str, refresh: bool = True,
                       skip_processed: bool = True) -> Dict:
        """翻译单个 Emby 条目并写回。
        演员锁定：只写回翻译后含中文且名字变化的；已处理条目默认跳过。
        返回 {changed, updates, error, skipped}
        """
        self._ensure_clients()
        from database import media_db
        if skip_processed and media_db.is_processed(str(item_id)):
            return {"changed": False, "skipped": "already_processed"}

        item = self.emby.get_item(item_id)
        if not item:
            return {"changed": False, "error": f"条目 {item_id} 不存在"}

        data = self._build_tmdb_data(item)
        # 标题字段 key 因类型而异：Movie 用 'title'，Series/Episode 用 'name'（与原版引擎一致）
        item_type = item.get("Type")
        title_key = "title" if item_type == "Movie" else "name"
        before_title = data.get(title_key)
        before_ov = data["overview"]

        # 豆瓣预取：先查豆瓣中文演员表（中文名+角色名），合并进翻译数据
        # 优化：仅当需要翻译演员/角色时才查（标题简介已中文+演员开关关 = 跳过，省时间）
        cfg_now = config_manager.APP_CONFIG
        need_actor = cfg_now.get("ai_translate_actor_role", False) or not self._has_cn(before_title or "")
        if need_actor:
            douban_cast = self._fetch_douban_cast(item)
            if douban_cast:
                self._merge_douban_cast(data, douban_cast)

        try:
            translate_tmdb_metadata_recursively(
                item_type="Movie" if item.get("Type") == "Movie" else "Series",
                tmdb_data=data,
                ai_translator=self.ai,
                item_name=item.get("Name") or "",
                tmdb_api_key=config_manager.APP_CONFIG.get("tmdb_api_key"),
                config=self._translation_config(),
            )
        except Exception as e:
            logger.error(f"翻译失败 [{item_id}]: {e}")
            media_db.record_failed(item_id, item.get("Name") or "",
                                   item.get("Type") or "", "translate_error", str(e))
            return {"changed": False, "error": str(e)}

        updates = {}
        # ★ 用 title_key 判断（Movie='title'，Series/Episode='name'），否则剧集标题翻译后被丢弃不写回
        new_title = data.get(title_key)
        if new_title and new_title != before_title:
            updates["Name"] = new_title
        if data.get("overview") and data["overview"] != before_ov:
            updates["Overview"] = data["overview"]

        # ★ 演员翻译写回：把翻译好的演员名+角色名写回 Emby People（原版 _process_cast_list 精简）
        # 安全网：只写翻译后含中文且确实变化的，保留头像/PersonId/顺序；角色名清"饰/配"前缀
        if config_manager.APP_CONFIG.get("ai_translate_actor_role", False):
            try:
                people_writeback = self._build_people_writeback(item, data)
                if people_writeback:
                    updates["People"] = people_writeback
            except Exception as e:
                logger.warning(f"演员写回构建失败（跳过，不影响标题/简介）: {e}")

        if not updates:
            # 无需变化也标记已处理（避免重复扫描烧 AI）
            media_db.mark_processed(item_id, item.get("Name") or "", item.get("Type") or "")
            return {"changed": False, "updates": {}}

        # 写回 Emby（批量时先等 Emby 空闲，防转码冲突）
        if self._wait_idle_before_write:
            self.emby.wait_for_server_idle(max_wait=60, check_interval=5)
        ok = self.emby.update_metadata(item_id, updates)
        if ok and refresh:
            self.emby.refresh_item(item_id)
        if ok:
            media_db.mark_processed(item_id, item.get("Name") or "", item.get("Type") or "")
        else:
            media_db.record_failed(item_id, item.get("Name") or "", item.get("Type") or "",
                                   "emby_write", "update_metadata failed")
        return {"changed": ok, "updates": updates}

    # ---------- 批量翻译（队列任务） ----------
    def batch_translate(self, item_type: str = "Movie", limit: int = 0,
                        refresh: bool = True, progress_cb=None,
                        skip_processed: bool = True, force: bool = False) -> Dict:
        """扫描并翻译一类条目。skip_processed: 跳过已处理；force: 忽略已处理全翻
        limit<=0 = 全库（分页扫描，每页500，防 Emby 过载）"""
        self._ensure_clients()
        from database import media_db
        self._wait_idle_before_write = True  # 批量模式启用 Emby 空闲等待

        # 分页扫描（每页 500），避免一次性拉全库打爆 Emby
        need = []
        scanned = 0
        page_size = 500
        start = 0
        from task_queue import task_queue as _scan_tq
        while True:
            page = self.emby.scan_items(item_type, limit=page_size, start=start)
            if not page:
                break
            scanned += len(page)
            page_need = [it for it in page if self.needs_translation(it)]
            need.extend(page_need)
            # 扫描进度报告
            try:
                _scan_tq.set_progress_current(
                    min(int(scanned / 21000 * 40), 40),
                    f"扫描 {scanned} 条中（待翻译 {len(need)}）...")
            except Exception:
                pass
            if limit and limit > 0 and scanned >= limit:
                break
            if len(page) < page_size:
                break
            start += page_size
            time.sleep(0.1)  # 分页间小延迟，防 Emby 过载
        # 截断到 limit
        if limit and limit > 0:
            need = need[:limit]

        if skip_processed and not force:
            before = len(need)
            need = [it for it in need if not media_db.is_processed(str(it["Id"]))]
            skipped_processed = before - len(need)
        else:
            skipped_processed = 0
        logger.info(f"[批量翻译] {item_type}: 扫描 {scanned} 条, 需翻译 {len(need)} 条"
                    f"(已处理跳过 {skipped_processed})")

        result = {"scanned": scanned, "need": len(need),
                  "changed": 0, "failed": 0, "skipped": skipped_processed, "items": []}
        # 分批处理（原版风格：batch_size=10，批间 2s 节流防 Emby 过载）
        batch_size = 10
        total = len(need)
        processed = 0
        for bstart in range(0, total, batch_size):
            # 停止检查
            from task_queue import task_queue
            if task_queue.is_cancelled():
                logger.info(f"⏹ 批量翻译 {item_type} 被用户停止（已处理 {processed}/{total}）")
                result["cancelled"] = True
                result["cancelled_at"] = processed
                break
            batch = need[bstart:bstart + batch_size]
            for idx_in_batch, item in enumerate(batch):
                iid = item["Id"]
                name = item.get("Name") or ""
                try:
                    r = self.translate_item(iid, refresh=refresh, skip_processed=False)
                    if r.get("changed"):
                        result["changed"] += 1
                        result["items"].append({"id": iid, "name": name,
                                                "to": r["updates"].get("Name", name)})
                        logger.info(f"  ✅ [{iid}] {name} → {r['updates'].get('Name', name)}")
                    elif r.get("skipped"):
                        result["skipped"] += 1
                    else:
                        result["items"].append({"id": iid, "name": name, "to": None})
                        logger.info(f"  [-] [{iid}] {name} 无需变化")
                except Exception as e:
                    result["failed"] += 1
                    media_db.record_failed(iid, name, item_type, "batch_error", str(e))
                    logger.error(f"  ❌ [{iid}] {name}: {e}")
                processed += 1
                # 进度（40%起，扫描占0-40%）
                pct = 40 + int(processed / max(total, 1) * 60)
                if progress_cb:
                    progress_cb(pct, f"翻译 {processed}/{total}: {name[:20]}")
                try:
                    from task_queue import task_queue as _tq
                    _tq.set_progress_current(pct, f"翻译 {processed}/{total}: {name[:20]}")
                except Exception:
                    pass
                time.sleep(0.1)
            # 批间节流：每批结束暂停 0.5 秒（原版几乎无延迟，仅轻保护）
            if bstart + batch_size < total:
                logger.info(f"  ⏳ 已处理 {processed}/{total}，批间暂停 0.5s")
                time.sleep(0.5)
        return result

    # ---------- 全库人物名翻译（原版 task_persons_translation 精简） ----------
    def translate_all_persons(self, limit: int = 0, progress_cb=None) -> Dict:
        """扫描 Emby 全部 Person → 非中文名 → AI 翻译 → 官方 API 写回。
        返回 {scanned, need_translate, updated, failed, skipped_cn, samples}
        """
        self._ensure_clients()
        result = {"scanned": 0, "need_translate": 0, "updated": 0,
                  "failed": 0, "skipped_cn": 0, "samples": []}
        self._wait_idle_before_write = True

        # 1. 扫描全库人物（分页）
        start = 0
        batch = 5000
        name_to_ids: Dict[str, list] = {}
        while True:
            from task_queue import task_queue as _tq
            if _tq.is_cancelled():
                logger.info(f"⏹ 人物扫描被用户停止（已扫 {result['scanned']} 人）")
                result["cancelled"] = True
                result["cancelled_at"] = result["scanned"]
                break
            persons, total = self.emby.get_persons(start=start, limit=batch)
            if not persons:
                break
            for p in persons:
                result["scanned"] += 1
                name = p.get("Name") or ""
                if not name:
                    continue
                if self._has_cjk(name):
                    result["skipped_cn"] += 1
                    continue
                name_to_ids.setdefault(name, []).append(p.get("Id"))
            # 进度无条件同步到全局任务状态（progress_cb 可能为 None）
            pct = min(int(result["scanned"] / max(total, 1) * 40), 40)
            txt = f"扫描人物 {result['scanned']}/{total}（待翻译 {len(name_to_ids)} 个名字）"
            if progress_cb:
                progress_cb(pct, txt)
            try:
                _tq.set_progress_current(pct, txt)
            except Exception:
                pass
            start += batch
            if start >= total or (limit and result["scanned"] >= limit):
                break

        result["need_translate"] = len(name_to_ids)
        if not name_to_ids:
            logger.info("全库人物已全部中文化，无需翻译")
            return result

        # 2. 批量翻译（fast 模式，一次 50 个）
        all_names = list(name_to_ids.keys())
        bsize = 50
        for i in range(0, len(all_names), bsize):
            from task_queue import task_queue
            if task_queue.is_cancelled():
                logger.info(f"⏹ 人物翻译被用户停止（已处理 {i}/{len(all_names)}）")
                result["cancelled"] = True
                if "cancelled_at" not in result:  # 扫描阶段已记录停止点则不覆盖
                    result["cancelled_at"] = i
                break
            batch_names = all_names[i:i + bsize]
            try:
                trans_map = self.ai.batch_translate(batch_names, mode="fast")
            except Exception as e:
                logger.error(f"人物翻译批次失败: {e}")
                result["failed"] += len(batch_names)
                continue
            if not isinstance(trans_map, dict):
                trans_map = {}
            # 3. 写回（白名单：只更新翻译后含中文的；10 线程并发，对齐原版）
            from concurrent.futures import ThreadPoolExecutor, as_completed
            update_tasks = []
            for orig, translated in trans_map.items():
                if not translated or not self._has_cn(str(translated)):
                    continue
                if str(translated).strip() == orig:
                    continue
                for pid in name_to_ids.get(orig, []):
                    update_tasks.append((pid, str(translated).strip()))
                if len(result["samples"]) < 5:
                    result["samples"].append(f"{orig} → {translated}")

            if update_tasks:
                # 写回前整个任务只等一次 Emby 空闲（原版无此等待；不再每演员阻塞）
                if self._wait_idle_before_write:
                    self.emby.wait_for_server_idle(max_wait=30, check_interval=5)
                    self._wait_idle_before_write = False

                executor = ThreadPoolExecutor(max_workers=10)
                try:
                    futures = {executor.submit(self.emby.update_person_details, pid, name): (pid, name)
                               for pid, name in update_tasks}
                    for fut in as_completed(futures):
                        if task_queue.is_cancelled():
                            logger.info("⏹ 人物写回被用户停止")
                            result["cancelled"] = True
                            if "cancelled_at" not in result:
                                result["cancelled_at"] = result["updated"]
                            for f in futures:  # 取消未启动的写回
                                f.cancel()
                            break
                        try:
                            if fut.result():
                                result["updated"] += 1
                            else:
                                result["failed"] += 1
                        except Exception:
                            result["failed"] += 1
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            pct2 = min(40 + int((i + bsize) / len(all_names) * 60), 99)
            txt2 = f"翻译写回 {min(i+bsize, len(all_names))}/{len(all_names)}"
            if progress_cb:
                progress_cb(pct2, txt2)
            # 同步到全局任务状态（UI 进度条）——progress_cb 可能为 None，必须无条件同步
            try:
                from task_queue import task_queue as _tq
                _tq.set_progress_current(pct2, txt2)
            except Exception:
                pass
        if progress_cb:
            progress_cb(100, f"完成: 更新 {result['updated']} 个")
            try:
                from task_queue import task_queue as _tq
                _tq.set_progress_current(100, f"完成: 更新 {result['updated']} 个")
            except Exception:
                pass
        logger.info(f"人物翻译完成: 扫描{result['scanned']} 需翻译{result['need_translate']} "
                    f"更新{result['updated']} 失败{result['failed']}")
        return result

    # ---------- webhook 实时翻译 ----------
    def handle_webhook(self, data: dict) -> Dict:
        """Emby webhook 事件处理：ItemAdded → 实时翻译"""
        event = data.get("Event") or data.get("event")
        item = data.get("Item") or {}
        item_id = str(item.get("Id") or "")
        item_name = item.get("Name") or ""
        item_type = item.get("Type") or ""

        if event not in ("ItemAdded", "Library.NewMediaItem", "item.added"):
            return {"handled": False, "reason": f"忽略事件 {event}"}

        if item_type not in ("Movie", "Series", "Episode"):
            return {"handled": False, "reason": f"忽略类型 {item_type}"}

        if not item_id:
            return {"handled": False, "reason": "无条目 ID"}

        logger.info(f"[webhook] 新入库: {item_type} [{item_id}] {item_name}，提交翻译任务")
        # 提交到队列（去重，避免重复事件）
        from task_queue import task_queue
        task_queue.submit(
            f"实时翻译 {item_name[:20]}",
            self.translate_item,
            item_id, True,
            dedup_key=f"webhook:{item_type}:{item_id}",
            timeout=300, retries=1,
        )
        return {"handled": True, "queued": True, "item_id": item_id, "name": item_name}


# 全局翻译服务
_service = None


def get_service() -> TranslateService:
    global _service
    if _service is None:
        _service = TranslateService()
    return _service


def reset_service():
    """重置全局 service（配置变更后调用，让 AI/Emby client 用新配置重建）"""
    global _service
    _service = None
    logger.info("全局 service 已重置（配置变更）")
