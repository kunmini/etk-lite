#!/usr/bin/env python3
"""
ETK 精简版 — 任务队列
特性: 单线程串行执行（防并发卡死）、去重、超时、失败重试、状态查询
"""
import logging
import queue
import threading
import time
import traceback
import uuid
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TaskQueue:
    def __init__(self, max_queue: int = 200):
        self._queue = queue.Queue(maxsize=max_queue)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()
        self._lock = threading.Lock()
        self._tasks: Dict[str, dict] = {}   # task_id -> task info
        self._pending_keys: set = set()     # 去重 key
        self._current: Optional[dict] = None
        self._idle = threading.Event()
        self._idle.set()

    # ---------- 提交 ----------
    def submit(self, name: str, fn: Callable, *args,
               dedup_key: str = "", timeout: int = 300,
               retries: int = 0, **kwargs) -> str:
        """提交任务。dedup_key 相同则合并（排队去重）"""
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            if dedup_key and dedup_key in self._pending_keys:
                logger.info(f"任务 [{name}] 已在队列中（去重: {dedup_key}），跳过")
                return ""
            if dedup_key:
                self._pending_keys.add(dedup_key)
            task = {
                "id": task_id, "name": name, "fn": fn, "args": args, "kwargs": kwargs,
                "timeout": timeout, "retries": retries, "dedup_key": dedup_key,
                "status": "queued", "created_at": time.time(),
                "started_at": None, "finished_at": None,
                "result": None, "error": None, "progress": 0, "progress_text": "",
                "cancel_requested": False, "total": 0, "done": 0,
            }
            self._tasks[task_id] = task
        try:
            self._queue.put(task_id, timeout=5)
        except queue.Full:
            with self._lock:
                self._tasks.pop(task_id, None)
                if dedup_key:
                    self._pending_keys.discard(dedup_key)
            logger.error("任务队列已满，丢弃任务")
            return ""
        return task_id

    # ---------- 工作线程 ----------
    def _run(self):
        while True:
            task_id = self._queue.get()
            with self._lock:
                task = self._tasks.get(task_id)
            if not task:
                continue
            self._idle.clear()
            self._current = task
            with self._lock:
                task["status"] = "running"
                task["started_at"] = time.time()
                task["last_progress_at"] = time.time()
                task["timed_out"] = False
            try:
                result_holder = {}

                def _target():
                    try:
                        result_holder["result"] = task["fn"](*task["args"], **task["kwargs"])
                        result_holder["ok"] = True
                    except Exception as e:
                        result_holder["error"] = e
                        result_holder["ok"] = False

                t = threading.Thread(target=_target, daemon=True)
                t.start()

                # ★ 软超时轮询：超时不杀任务（子线程无法强杀），改为标记 timed_out
                # 继续等真实结果；只有【超时 + 长时间无进度】才判定卡死 → failed + 释放去重
                while t.is_alive():
                    with self._lock:
                        elapsed = time.time() - task["started_at"]
                        last_prog = task.get("last_progress_at") or task["started_at"]
                    if elapsed > task["timeout"]:
                        idle = time.time() - last_prog
                        if idle > 120:  # 超时后 120s 无任何进度更新 = 真卡死
                            task["error"] = (f"任务卡死（已运行 {int(elapsed)}s，"
                                             f"最后进度更新 {int(idle)}s 前），已释放。可重新提交。")
                            task["status"] = "failed"
                            break
                        if not task.get("timed_out"):
                            task["timed_out"] = True
                            logger.info(f"任务 [{task['name']}] 超过 {task['timeout']}s 仍在执行（软超时，继续等待）")
                    t.join(timeout=0.5)  # 等子线程 0.5s（结束即返回，延迟最小）

                if t.is_alive():
                    # 卡死分支：无法强杀 daemon 线程，释放去重键让用户重试
                    task["finished_at"] = time.time()
                    with self._lock:
                        if task["dedup_key"]:
                            self._pending_keys.discard(task["dedup_key"])
                    self._current = None
                    self._idle.set()
                    self._queue.task_done()
                    continue

                t.join()
                if result_holder.get("ok"):
                    task["result"] = result_holder.get("result")
                    # 若结果里有 cancelled 标记，显示为已停止
                    if isinstance(result_holder.get("result"), dict) and result_holder["result"].get("cancelled"):
                        task["status"] = "cancelled"
                    else:
                        task["status"] = "success"
                else:
                    err = result_holder.get("error")
                    task["error"] = str(err)
                    # 重试
                    if task["retries"] > 0:
                        task["retries"] -= 1
                        task["status"] = "queued"
                        self._queue.put(task_id)
                        self._idle.set()
                        self._current = None
                        continue
                    task["status"] = "failed"
            except Exception as e:
                task["error"] = f"{e}\n{traceback.format_exc()}"
                task["status"] = "failed"
            finally:
                task["finished_at"] = time.time()
                with self._lock:
                    if task["dedup_key"]:
                        self._pending_keys.discard(task["dedup_key"])
                self._current = None
                self._idle.set()
                self._queue.task_done()

    # ---------- 状态 ----------
    # ---------- 停止任务 ----------
    def cancel(self, task_id: str = "") -> bool:
        """请求停止任务。task_id 为空则停止当前任务。
        返回 True=已请求停止（任务会在下一个检查点退出）
        """
        with self._lock:
            if task_id and task_id in self._tasks:
                self._tasks[task_id]["cancel_requested"] = True
                return True
            if self._current and (not task_id or self._current["id"] == task_id):
                self._current["cancel_requested"] = True
                return True
            return False

    def is_cancelled(self) -> bool:
        """供任务内部检查是否被请求停止"""
        with self._lock:
            if self._current and self._current.get("cancel_requested"):
                return True
        return False

    def get_status(self) -> dict:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda x: x["created_at"])
            def _sanitize(t):
                """去掉不可序列化的字段"""
                return {k: v for k, v in t.items() if k not in ("fn", "args", "kwargs")}
            return {
                "current": _sanitize(self._current) if self._current else None,
                "queue_size": self._queue.qsize(),
                "tasks": [_sanitize(t) for t in tasks[-50:]],
            }

    def wait_idle(self, timeout: float = 60) -> bool:
        return self._idle.wait(timeout)

    def set_progress(self, task_id: str, progress: int, text: str = ""):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["progress"] = progress
                task["progress_text"] = text

    def set_progress_current(self, progress: int, text: str = ""):
        """更新当前运行任务的进度（供任务内部调用，UI 进度条用）"""
        with self._lock:
            if self._current:
                self._current["progress"] = progress
                self._current["progress_text"] = text
                self._current["done"] = progress
                self._current["total"] = 100
                self._current["last_progress_at"] = time.time()  # 卡死检测依据

    def clear_history(self) -> int:
        """清空已完成/已停止的历史任务，保留当前运行中的。返回清除了多少个。"""
        with self._lock:
            current_id = self._current["id"] if self._current else None
            removed = 0
            to_remove = []
            for tid, t in self._tasks.items():
                if tid == current_id:
                    continue  # 当前运行中的不动
                status = t.get("status")
                if status in ("success", "failed", "cancelled"):
                    to_remove.append(tid)
            for tid in to_remove:
                self._tasks.pop(tid, None)
                removed += 1
            return removed


# 全局任务队列
task_queue = TaskQueue()
