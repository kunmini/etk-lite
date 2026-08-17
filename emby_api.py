#!/usr/bin/env python3
"""
ETK 精简版 — Emby API 读写 + 刷新（服务版核心）
"""
import logging
import os
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

HEADERS = {'X-Emby-Authorization':
           'MediaBrowser Client="etk-lite", Device="etk", DeviceId="etk01", Version="1.0"'}


class EmbyAPI:
    def __init__(self, url: str, username: str = "root", password: str = "123",
                 api_key: str = ""):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.api_key = api_key  # 优先用 API Key（若有）
        self.token = None
        self.user_id = None

    def login(self) -> bool:
        """登录：优先 API Key 直连（X-Emby-Token），否则账密换 token"""
        # 方式1: API Key（Emby 后台生成的，直接可用）
        if self.api_key:
            try:
                r = requests.get(f"{self.url}/System/Info",
                                 headers={"X-Emby-Token": self.api_key}, timeout=10)
                if r.status_code == 200:
                    self.token = self.api_key
                    # 用默认管理员（无 user_id 也能查 /Users/{id} 之外的）
                    self.user_id = self._find_first_user() or ""
                    return True
            except Exception as e:
                logger.warning(f"API Key 直连失败（回退账密登录）: {e}")
        # 方式2: 账密登录
        try:
            r = requests.post(f"{self.url}/Users/AuthenticateByName",
                              headers=HEADERS,
                              json={"Username": self.username, "Pw": self.password},
                              timeout=15)
            r.raise_for_status()
            data = r.json()
            self.token = data["AccessToken"]
            self.user_id = data["User"]["Id"]
            return True
        except Exception as e:
            logger.error(f"Emby 登录失败: {e}")
            return False

    def _find_first_user(self) -> str:
        """API Key 模式下找一个可用 UserId（查条目需要）"""
        try:
            r = requests.get(f"{self.url}/Users",
                             headers={"X-Emby-Token": self.token}, timeout=10)
            if r.status_code == 200:
                users = r.json() or []
                for u in users:
                    if u.get("Policy", {}).get("IsAdministrator"):
                        return u.get("Id", "")
                return users[0].get("Id", "") if users else ""
        except Exception:
            pass
        return ""

    def _get(self, path: str, **params) -> Optional[dict]:
        if not self.token:
            self.login()
        params["api_key"] = self.token
        try:
            r = requests.get(f"{self.url}{path}", params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Emby GET {path} 失败: {e}")
            return None

    def _post(self, path: str, body: dict = None, **params) -> bool:
        if not self.token:
            self.login()
        params["api_key"] = self.token
        try:
            r = requests.post(f"{self.url}{path}", params=params,
                              json=body or {}, timeout=30)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Emby POST {path} 失败: {e}")
            return False

    # ---------- 查询 ----------
    def scan_items(self, item_type: str, limit: int = 0, start: int = 0,
                   fields: str = "Overview,OriginalTitle,Taglines") -> List[dict]:
        # limit <= 0 = 全库（不传 Limit 参数，Emby 返回全部）
        params = {"Recursive": "true", "IncludeItemTypes": item_type,
                  "Fields": fields, "SortBy": "DateCreated", "SortOrder": "Descending"}
        if limit and limit > 0:
            params["Limit"] = limit
        if start and start > 0:
            params["StartIndex"] = start
        data = self._get(f"/Users/{self.user_id}/Items", **params)
        return (data or {}).get("Items", [])

    def get_item(self, item_id: str,
                 fields: str = "Overview,OriginalTitle,Taglines,People") -> Optional[dict]:
        return self._get(f"/Users/{self.user_id}/Items/{item_id}", Fields=fields)

    def get_item_by_tmdb(self, tmdb_id: str, item_type: str) -> Optional[dict]:
        """按 TMDb ID 查 Emby 条目（webhook 实时翻译用）"""
        data = self._get(f"/Users/{self.user_id}/Items", Recursive="true",
                         IncludeItemTypes=item_type, Limit=10,
                         AnyProviderIdEquals=f"tmdb:{tmdb_id}")
        items = (data or {}).get("Items", [])
        return items[0] if items else None

    # ---------- 人物 ----------
    def get_persons(self, start: int = 0, limit: int = 500) -> tuple:
        """拉取 Emby 全部人物（分页）。返回 (items, total)"""
        data = self._get("/Persons", StartIndex=start, Limit=limit,
                         Fields="ProviderIds,Name")
        if not data:
            return [], 0
        return data.get("Items", []), data.get("TotalRecordCount", 0)

    def update_person_details(self, person_id: str, new_name: str) -> bool:
        """更新人物名（官方 API：GET→改 Name→POST 全量回写）"""
        if not self.token:
            self.login()
        try:
            r = requests.get(f"{self.url}/Users/{self.user_id}/Items/{person_id}",
                             params={"api_key": self.token}, timeout=30)
            r.raise_for_status()
            person = r.json()
        except Exception as e:
            logger.error(f"GET 人物 {person_id} 失败: {e}")
            return False
        person["Name"] = new_name
        try:
            r = requests.post(f"{self.url}/Items/{person_id}",
                              params={"api_key": self.token},
                              json=person, timeout=30)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.error(f"更新人物 {person_id} 失败: {e}")
            return False

    # ---------- 演员管理（增加/删除/补充） ----------
    def get_people(self, item_id: str) -> List[dict]:
        """获取条目的演员/导演列表（People 字段）"""
        item = self.get_item(item_id, fields="People,Name")
        if not item:
            return []
        return item.get("People", []) or []

    def delete_person_shenyi(self, person_id: str) -> bool:
        """删除演员（神医 Pro 插件接口 /Items/{Id}/DeletePerson）"""
        try:
            r = requests.post(f"{self.url}/Items/{person_id}/DeletePerson",
                              params={"api_key": self.token}, timeout=15)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.error(f"删除演员失败（需神医插件）: {e}")
            return False

    def update_people_full(self, item_id: str, people: List[dict]) -> bool:
        """全量写回条目人物表（GET 完整条目 → 改 People → POST 回写）"""
        try:
            r = requests.get(f"{self.url}/Users/{self.user_id}/Items/{item_id}",
                             params={"api_key": self.token, "Fields": "People,Overview"},
                             timeout=15)
            if r.status_code != 200:
                logger.error(f"GET 条目失败: {r.status_code}")
                return False
            item = r.json()
            item["People"] = people
            r2 = requests.post(f"{self.url}/Items/{item_id}",
                               params={"api_key": self.token},
                               json=item, timeout=15)
            if r2.status_code in (200, 204):
                logger.info(f"✅ 人物表已写回 {item_id}: {len(people)} 人")
                return True
            logger.error(f"写回失败: {r2.status_code} {r2.text[:100]}")
            return False
        except Exception as e:
            logger.error(f"更新人物表失败: {e}")
            return False

    def add_person(self, item_id: str, name: str, role: str = "",
                   ptype: str = "Actor") -> bool:
        """添加演员到条目（读当前 → 追加 → 写回）"""
        people = self.get_people(item_id)
        # 去重（同名+同角色不重复加）
        for p in people:
            if p.get("Name") == name and p.get("Role", "") == role:
                logger.info(f"演员已存在: {name} ({role})")
                return True
        people.append({"Name": name, "Role": role, "Type": ptype})
        return self.update_people_full(item_id, people)

    def remove_person(self, item_id: str, person_id: str = "", name: str = "") -> bool:
        """从条目删除演员：优先神医接口（按 ID），否则全量重写（按名字）"""
        if person_id and self.delete_person_shenyi(person_id):
            return True
        # 回退：全量重写（按名字删）
        people = self.get_people(item_id)
        if not name:
            for p in people:
                if p.get("Id") == person_id:
                    name = p.get("Name", "")
                    break
        new_people = [p for p in people if p.get("Name") != name and p.get("Id") != person_id]
        if len(new_people) == len(people):
            logger.info(f"未找到演员可删: {name or person_id}")
            return False
        return self.update_people_full(item_id, new_people)

    # ---------- 写回 ----------
    def wait_for_server_idle(self, max_wait: int = 120, check_interval: int = 5) -> bool:
        """等待 Emby 空闲（无转码/无活动会话）再写库，防冲突。
        返回 True=已空闲/超时，False=Emby 不可达
        """
        import time as _t
        deadline = _t.time() + max_wait
        while _t.time() < deadline:
            try:
                # 查询活动转码会话
                r = requests.get(f"{self.url}/Sessions/Active",
                                 params={"api_key": self.token}, timeout=10)
                if r.status_code == 200:
                    sessions = r.json() or []
                    active = [s for s in sessions
                              if s.get("NowPlayingItem") or s.get("TranscodingInfo")]
                    if not active:
                        return True
                    logger.debug(f"Emby 忙: {len(active)} 个活动会话，等待...")
                else:
                    return True  # 接口异常，不阻塞（宁可写库）
            except Exception as e:
                logger.debug(f"查询 Emby 会话失败（不阻塞）: {e}")
                return True
            _t.sleep(check_interval)
        logger.warning(f"等待 Emby 空闲超时（{max_wait}s），继续执行")
        return True

    def update_metadata(self, item_id: str, updates: dict) -> bool:
        """更新条目元数据。
        Emby 4.9 要求: GET 完整条目 → 修改字段 → POST 完整对象回写
        （只传 Name/Overview 会 400）
        """
        if not self.token:
            self.login()
        # 1. GET 完整条目
        try:
            r = requests.get(f"{self.url}/Users/{self.user_id}/Items/{item_id}",
                             params={"api_key": self.token}, timeout=30)
            r.raise_for_status()
            full = r.json()
        except Exception as e:
            logger.error(f"GET 条目 {item_id} 失败: {e}")
            return False
        # 2. 修改字段
        for k, v in updates.items():
            if v is not None:
                full[k] = v
        # 3. POST 完整对象回写
        try:
            r = requests.post(f"{self.url}/Items/{item_id}",
                              params={"api_key": self.token},
                              json=full, timeout=30)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.error(f"更新条目 {item_id} 失败: {e}")
            return False

    def refresh_item(self, item_id: str, metadata_only: bool = True) -> bool:
        """通知 Emby 刷新条目（翻译后调用，让 Emby 重读并落盘 NFO）。
        对齐原版：MetadataRefreshMode=FullRefresh + 剧集自动递归刷新分集。
        """
        # 判断是否剧集（剧集需递归刷新，刷出分集字幕/元数据）
        recursive = False
        try:
            r = requests.get(f"{self.url}/Users/{self.user_id}/Items/{item_id}",
                             params={"api_key": self.token}, timeout=15)
            if r.status_code == 200:
                recursive = (r.json().get("Type") == "Series")
        except Exception:
            pass
        body = {
            "MetadataRefreshMode": "FullRefresh",
            "ImageRefreshMode": "ValidationOnly" if metadata_only else "FullRefresh",
            "ReplaceAllMetadata": False,
            "ReplaceAllImages": False,
        }
        return self._post(f"/Items/{item_id}/Refresh", body,
                          Recursive=str(recursive).lower())
