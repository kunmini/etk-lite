#!/usr/bin/env python3
"""
ETK 精简版 — 定时任务（APScheduler）
支持: 每天定时批量翻译电影/剧集/人物
配置存 app_settings（UI 可改）
"""
import logging
import os
from typing import Optional

from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        _scheduler.start()
    return _scheduler


def _run_batch(item_type: str):
    """定时触发的批量翻译任务"""
    from task_queue import task_queue
    from translate_service import get_service
    service = get_service()
    logger.info(f"[定时任务] 开始批量翻译 {item_type}")
    task_queue.submit(
        name=f"定时翻译{item_type}",
        fn=service.batch_translate,
        args=(item_type, 5000, True, None, True, False),
        dedup_key=f"sched:{item_type}",
        timeout=7200, retries=0,
    )


def _run_persons():
    from task_queue import task_queue
    from translate_service import get_service
    service = get_service()
    logger.info("[定时任务] 开始全库人物翻译")
    task_queue.submit(
        name="定时人物翻译",
        fn=service.translate_all_persons,
        args=(0, None),
        dedup_key="sched:persons",
        timeout=7200, retries=0,
    )


def setup_scheduled_jobs():
    """从配置读取定时计划并注册（幂等：先清空再注册）"""
    from database import connection, settings_db
    connection.init_db()
    sched = get_scheduler()
    # 清空已有任务（防重复注册）
    for job in list(sched.get_jobs()):
        job.remove()

    cfg = settings_db.get_setting("scheduled_tasks") or {}
    if not isinstance(cfg, dict):
        cfg = {}

    # 定时批量翻译电影
    movie_cron = cfg.get("movie_cron") or "0 4 * * *"
    movie_enabled = cfg.get("movie_enabled", True)
    if movie_enabled and movie_cron:
        sched.add_job(_run_batch, CronTrigger.from_crontab(movie_cron),
                      args=["Movie"], id="sched_movie", replace_existing=True)
        logger.info(f"[定时任务] 电影翻译: {movie_cron}")

    # 定时批量翻译剧集
    series_cron = cfg.get("series_cron") or "0 5 * * *"
    series_enabled = cfg.get("series_enabled", True)
    if series_enabled and series_cron:
        sched.add_job(_run_batch, CronTrigger.from_crontab(series_cron),
                      args=["Series"], id="sched_series", replace_existing=True)
        logger.info(f"[定时任务] 剧集翻译: {series_cron}")

    # 定时人物翻译
    persons_cron = cfg.get("persons_cron") or "0 6 * * 0"
    persons_enabled = cfg.get("persons_enabled", False)
    if persons_enabled and persons_cron:
        sched.add_job(_run_persons, CronTrigger.from_crontab(persons_cron),
                      id="sched_persons", replace_existing=True)
        logger.info(f"[定时任务] 人物翻译: {persons_cron}")

    return sched
