"""ETK 精简版 tasks/helpers — 只保留翻译引擎"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple, Any

from ai_translator import AITranslator
from database import connection
from database import actor_db, media_db, tmdb_collection_db
from handler.tmdb import get_movie_details, get_tv_details, get_collection_details
import utils
import constants

logger = logging.getLogger(__name__)

# =====================================================================
# 以下 translate_tmdb_metadata_recursively 为原版函数（未修改）
# =====================================================================

def translate_tmdb_metadata_recursively(
    item_type: str,
    tmdb_data: Dict[str, Any],
    ai_translator: Any,
    item_name: str = "",
    tmdb_api_key: str = None,
    config: dict = None
):
    """
    【终极大一统翻译引擎】
    递归翻译 TMDb 数据的标题、简介、标语。
    地毯式翻译所有主创、导演、演员、客串明星的【姓名】和【角色名】。
    """
    if not ai_translator or not tmdb_data or not config:
        return

    pending_items = {}
    pending_persons = set()
    pending_roles = set()
    collections_to_upsert = []
    translated_count = 0

    # ★ 统计计数器
    stats = {
        'original_cast_count': 0,
        'truncated_cast_count': 0,

        # 待处理词条总数：缓存命中 + 实际提交
        'title_pending_count': 0,
        'overview_pending_count': 0,
        'tagline_pending_count': 0,
        'person_pending_count': 0,
        'role_pending_count': 0,

        # 实际提交 AI 的数量
        'title_needs_translation': 0,
        'overview_needs_translation': 0,
        'tagline_needs_translation': 0,
        'person_ai_calls': 0,
        'role_ai_calls': 0,

        # 缓存命中
        'title_cache_hits': 0,
        'overview_cache_hits': 0,
        'tagline_cache_hits': 0,
        'person_cache_hits': 0,
        'role_cache_hits': 0,
    }

    translate_title_enabled = config.get(constants.CONFIG_OPTION_AI_TRANSLATE_TITLE, False)
    translate_overview_enabled = config.get(constants.CONFIG_OPTION_AI_TRANSLATE_OVERVIEW, False)
    translate_ep_overview_enabled = config.get(constants.CONFIG_OPTION_AI_TRANSLATE_EPISODE_OVERVIEW, False)
    translate_actor_enabled = config.get(constants.CONFIG_OPTION_AI_TRANSLATE_ACTOR_ROLE, False)
    remove_no_avatar = config.get(constants.CONFIG_OPTION_REMOVE_ACTORS_WITHOUT_AVATARS, True)
    skip_tagline_translation = bool(config.get('_watchlist_skip_tagline_translation', False))

    # --- 1. 收集与缓存检查阶段 ---
    def _collect_single_item(data_dict: Dict, specific_item_type: str):
        current_tmdb_id = data_dict.get('id')
        if not current_tmdb_id:
            return

        tmdb_id_str = str(current_tmdb_id)
        title_key = 'title' if specific_item_type == 'Movie' else 'name'

        local_info = media_db.get_local_translation_info(tmdb_id_str, specific_item_type)

        needs_title = False
        needs_overview = False
        needs_tagline = False

        # A. 检查简介 Overview
        is_ep = specific_item_type == 'Episode'
        if (not is_ep and translate_overview_enabled) or (is_ep and translate_ep_overview_enabled):
            overview = data_dict.get('overview')
            if not overview or not utils.contains_chinese(overview):
                if local_info and local_info.get('overview') and utils.contains_chinese(local_info['overview']):
                    data_dict['overview'] = local_info['overview']
                    stats['overview_pending_count'] += 1
                    stats['overview_cache_hits'] += 1
                else:
                    if not overview and tmdb_api_key:
                        try:
                            if specific_item_type == 'Movie':
                                en_data = get_movie_details(int(tmdb_id_str), tmdb_api_key, language="en-US")
                                data_dict['overview'] = en_data.get('overview', '')
                            elif specific_item_type == 'Series':
                                en_data = get_tv_details(int(tmdb_id_str), tmdb_api_key, language="en-US")
                                data_dict['overview'] = en_data.get('overview', '')
                        except Exception:
                            pass

                    if data_dict.get('overview'):
                        needs_overview = True
                        stats['overview_pending_count'] += 1
                        stats['overview_needs_translation'] += 1

        # B. 检查标题 Title
        if translate_title_enabled:
            current_title = data_dict.get(title_key)
            if current_title and not utils.contains_chinese(current_title):
                if local_info and local_info.get('title') and utils.contains_chinese(local_info['title']):
                    data_dict[title_key] = local_info['title']
                    stats['title_pending_count'] += 1
                    stats['title_cache_hits'] += 1
                else:
                    needs_title = True
                    stats['title_pending_count'] += 1
                    stats['title_needs_translation'] += 1

        # C. 检查标语 Tagline
        # 追剧刷新会传入 _watchlist_skip_tagline_translation，避免只为标语额外拉取英文并消耗 AI token。
        if (not skip_tagline_translation) and translate_title_enabled and specific_item_type in ['Movie', 'Series']:
            tagline = data_dict.get('tagline')
            if not tagline or not utils.contains_chinese(tagline):
                # 先用本地缓存回填，避免重复翻译
                if local_info and local_info.get('tagline') and utils.contains_chinese(local_info['tagline']):
                    data_dict['tagline'] = local_info['tagline']
                    stats['tagline_pending_count'] += 1
                    stats['tagline_cache_hits'] += 1
                else:
                    # 本地没有中文标语，再去补英文原文，准备送翻译
                    if not tagline and tmdb_api_key:
                        try:
                            if specific_item_type == 'Movie':
                                en_data = get_movie_details(int(tmdb_id_str), tmdb_api_key, language="en-US")
                                data_dict['tagline'] = en_data.get('tagline', '')
                            elif specific_item_type == 'Series':
                                en_data = get_tv_details(int(tmdb_id_str), tmdb_api_key, language="en-US")
                                data_dict['tagline'] = en_data.get('tagline', '')
                        except Exception:
                            pass

                    if data_dict.get('tagline'):
                        needs_tagline = True
                        stats['tagline_pending_count'] += 1
                        stats['tagline_needs_translation'] += 1

        if needs_title or needs_overview or needs_tagline:
            pending_items[tmdb_id_str] = {
                "type": specific_item_type,
                "title_key": title_key,
                "title": data_dict.get(title_key) if needs_title else None,
                "overview": data_dict.get('overview') if needs_overview else None,
                "tagline": data_dict.get('tagline') if needs_tagline else None,
                "ref": data_dict
            }

        # D. 收集人物和角色
        if translate_actor_enabled:
            credits_data = data_dict.get('credits') or data_dict.get('aggregate_credits') or data_dict.get('casts') or {}

            for crew_member in credits_data.get('crew', []):
                if crew_member.get('job') in ['Director', 'Series Director']:
                    name = crew_member.get('name')
                    if name and not utils.contains_chinese(name):
                        pending_persons.add(name)

            max_actors = config.get(constants.CONFIG_OPTION_MAX_ACTORS_TO_PROCESS, 30)  # 最大演员数配置，默认30
            max_ep_actors = config.get(constants.CONFIG_OPTION_MAX_EPISODE_ACTORS_TO_PROCESS, 0) # 最大分集演员数配置，默认0（即分集不处理演员）
            
            try:
                limit = int(max_actors)
                if limit <= 0: limit = 30
            except Exception:
                limit = 30
                
            try:
                ep_limit = int(max_ep_actors)
            except Exception:
                ep_limit = 0

            def _smart_truncate(actor_list, max_limit):
                if not actor_list: return []
                stats['original_cast_count'] += len(actor_list)
                valid_actors = [a for a in actor_list if a.get('profile_path')] if remove_no_avatar else actor_list
                valid_actors.sort(key=lambda x: x.get('order') if x.get('order') is not None else 999)
                truncated = valid_actors[:max_limit]
                stats['truncated_cast_count'] += len(truncated)
                return truncated

            # ★★★ 核心优化：如果是分集，且配置为 0，直接清空演员表，不送去翻译 ★★★
            if specific_item_type == 'Episode' and ep_limit == 0:
                if 'cast' in credits_data: credits_data['cast'] = []
                if 'guest_stars' in credits_data: credits_data['guest_stars'] = []
            else:
                # 动态决定当前层级的限制人数
                current_limit = ep_limit if specific_item_type == 'Episode' else limit
                guest_limit = ep_limit if specific_item_type == 'Episode' else 10
                
                if 'cast' in credits_data:
                    credits_data['cast'] = _smart_truncate(credits_data['cast'], current_limit)
                if 'guest_stars' in credits_data:
                    credits_data['guest_stars'] = _smart_truncate(credits_data['guest_stars'], guest_limit)

            all_actors = credits_data.get('cast', []) + credits_data.get('guest_stars', [])
            for actor in all_actors:
                name = actor.get('name')
                if name and not utils.contains_chinese(name):
                    pending_persons.add(name)

                character = actor.get('character')
                if character:
                    cleaned_char = utils.clean_character_name_static(character)
                    if cleaned_char and not utils.contains_chinese(cleaned_char):
                        pending_roles.add(cleaned_char)

        # E. 检查电影所属合集 (Collection)
        if specific_item_type == 'Movie' and data_dict.get('belongs_to_collection'):
            coll_info = data_dict['belongs_to_collection']
            coll_id = str(coll_info.get('id'))
            if coll_id:
                from database import tmdb_collection_db
                from handler.tmdb import get_collection_details
                
                # 1. 查本地数据库是否已有该合集
                cached_coll = tmdb_collection_db.get_native_collection_by_tmdb_id(coll_id)
                if cached_coll and cached_coll.get('overview'):
                    # 已有缓存，直接回填
                    coll_info['name'] = cached_coll.get('name') or coll_info.get('name')
                    coll_info['overview'] = cached_coll.get('overview')
                else:
                    # 2. 无缓存，去 TMDb 拉取完整合集信息 (为了拿到 overview 和 parts)
                    if tmdb_api_key:
                        full_coll = get_collection_details(int(coll_id), tmdb_api_key)
                        if full_coll:
                            coll_info['overview'] = full_coll.get('overview', '')
                            coll_info['poster_path'] = full_coll.get('poster_path')
                            coll_info['backdrop_path'] = full_coll.get('backdrop_path')
                            # 顺便把 parts 里的电影 ID 提取出来，准备后续占坑
                            coll_info['all_tmdb_ids'] = [str(p.get('id')) for p in full_coll.get('parts', []) if p.get('id')]
                            
                            collections_to_upsert.append(coll_info) # 标记需要入库
                            
                            # 3. 加入待翻译队列
                            needs_coll_title = False
                            needs_coll_overview = False
                            
                            if translate_title_enabled:
                                c_name = coll_info.get('name')
                                if c_name and not utils.contains_chinese(c_name):
                                    needs_coll_title = True
                                    stats['title_pending_count'] += 1
                                    stats['title_needs_translation'] += 1
                                    
                            if translate_overview_enabled:
                                c_overview = coll_info.get('overview')
                                if c_overview and not utils.contains_chinese(c_overview):
                                    needs_coll_overview = True
                                    stats['overview_pending_count'] += 1
                                    stats['overview_needs_translation'] += 1
                                    
                            if needs_coll_title or needs_coll_overview:
                                pending_items[f"coll_{coll_id}"] = {
                                    "type": "Collection",
                                    "title_key": "name",
                                    "title": coll_info.get('name') if needs_coll_title else None,
                                    "overview": coll_info.get('overview') if needs_coll_overview else None,
                                    "tagline": None,
                                    "ref": coll_info
                                }

    # --- 遍历收集 ---
    if item_type == 'Movie':
        _collect_single_item(tmdb_data, 'Movie')

    elif item_type == 'Series':
        series_details = tmdb_data.get('series_details', tmdb_data)
        _collect_single_item(series_details, 'Series')

        for season in tmdb_data.get("seasons_details", []):
            _collect_single_item(season, 'Season')

        episodes_container = tmdb_data.get("episodes_details", {})
        episodes_list = episodes_container.values() if isinstance(episodes_container, dict) else episodes_container
        for ep in episodes_list:
            _collect_single_item(ep, 'Episode')

    # ★ 收集完成后，记录人物/角色待翻词条总数
    stats['person_pending_count'] = len(pending_persons)
    stats['role_pending_count'] = len(pending_roles)

    # --- 2. 批量翻译阶段 ---
    BATCH_SIZE = 20

    if pending_items:
        logger.info("  ➜ [AI翻译引擎] 开始进行翻译...")

        # 1. 翻译简介
        overviews_to_translate = {k: v["overview"] for k, v in pending_items.items() if v["overview"]}
        if overviews_to_translate:
            items_list = list(overviews_to_translate.items())
            for i in range(0, len(items_list), BATCH_SIZE):
                batch_dict = dict(items_list[i:i + BATCH_SIZE])
                trans_results = ai_translator.batch_translate_overviews(batch_dict, context_title=item_name)

                for tid, trans_text in trans_results.items():
                    if trans_text and utils.contains_chinese(trans_text) and tid in pending_items:
                        pending_items[tid]["ref"]['overview'] = trans_text
                        translated_count += 1

                import time
                time.sleep(1)

        # 2. 翻译标语
        taglines_to_translate = {k: v["tagline"] for k, v in pending_items.items() if v["tagline"]}
        if taglines_to_translate:
            items_list = list(taglines_to_translate.items())
            for i in range(0, len(items_list), BATCH_SIZE):
                batch_dict = dict(items_list[i:i + BATCH_SIZE])
                trans_results = ai_translator.batch_translate_overviews(batch_dict, context_title=item_name)

                for tid, trans_text in trans_results.items():
                    if trans_text and utils.contains_chinese(trans_text) and tid in pending_items:
                        pending_items[tid]["ref"]['tagline'] = trans_text
                        translated_count += 1

                import time
                time.sleep(1)

        # 3. 翻译标题
        titles_to_translate = {k: v["title"] for k, v in pending_items.items() if v["title"]}
        if titles_to_translate:
            items_list = list(titles_to_translate.items())
            for i in range(0, len(items_list), BATCH_SIZE):
                batch_dict = dict(items_list[i:i + BATCH_SIZE])
                trans_results = ai_translator.batch_translate_titles(batch_dict, media_type="Episode")

                for tid, trans_text in trans_results.items():
                    if trans_text and utils.contains_chinese(trans_text) and tid in pending_items:
                        title_key = pending_items[tid]["title_key"]
                        pending_items[tid]["ref"][title_key] = trans_text
                        translated_count += 1

                import time
                time.sleep(1)

    # --- 3. 翻译人物姓名和角色名 ---
    if pending_persons or pending_roles:
        person_trans_map = {}
        role_trans_map = {}

        from database import actor_db
        db_manager = actor_db.ActorDBManager()

        role_translation_mode = config.get(constants.CONFIG_OPTION_AI_TRANSLATION_MODE, 'fast')

        item_title = tmdb_data.get('title') or tmdb_data.get('name') or item_name
        item_year = None
        release_date = tmdb_data.get('release_date') or tmdb_data.get('first_air_date')
        if release_date and len(release_date) >= 4:
            item_year = release_date[:4]

        with connection.get_db_connection() as conn:
            with conn.cursor() as cursor:

                # 人名：固定音译模式 + 强制缓存
                if pending_persons:
                    api_list = []

                    for name in pending_persons:
                        cached = db_manager.get_translation_from_db(cursor, name)
                        if cached and cached.get('translated_text'):
                            person_trans_map[name] = cached['translated_text']
                            stats['person_cache_hits'] += 1
                        else:
                            api_list.append(name)

                    stats['person_ai_calls'] = len(api_list)

                    if api_list:
                        logger.info(
                            f"  ➜ [AI翻译引擎] 提交 {len(api_list)} 个人物姓名进行翻译 "
                            f"(模式: transliterate, 缓存命中: {stats['person_cache_hits']})..."
                        )

                        for i in range(0, len(api_list), BATCH_SIZE):
                            batch_names = api_list[i:i + BATCH_SIZE]
                            trans_results = ai_translator.batch_translate(batch_names, mode='transliterate')

                            if isinstance(trans_results, list) and len(trans_results) == len(batch_names):
                                trans_results = {
                                    batch_names[j]: trans_results[j]
                                    for j in range(len(batch_names))
                                }
                            elif not isinstance(trans_results, dict):
                                trans_results = {}

                            for k, v in trans_results.items():
                                if isinstance(v, (list, tuple, set)):
                                    v = next((x for x in v if isinstance(x, str) and x.strip()), None)

                                if not v:
                                    continue

                                v = str(v).strip()

                                if v and utils.contains_chinese(v):
                                    person_trans_map[k] = v
                                    db_manager.save_translation_to_db(cursor, k, v, ai_translator.provider)

                            import time
                            time.sleep(1)

                # 角色名：根据配置模式，顾问模式跳过缓存
                if pending_roles:
                    api_list = []

                    if role_translation_mode == 'quality':
                        api_list = list(pending_roles)
                    else:
                        for role in pending_roles:
                            cached = db_manager.get_translation_from_db(cursor, role)
                            if cached and cached.get('translated_text'):
                                role_trans_map[role] = cached['translated_text']
                                stats['role_cache_hits'] += 1
                            else:
                                api_list.append(role)

                    stats['role_ai_calls'] = len(api_list)

                    if api_list:
                        logger.info(
                            f"  ➜ [AI翻译引擎] 提交 {len(api_list)} 个角色名进行翻译 "
                            f"(模式: {role_translation_mode}, 缓存命中: {stats['role_cache_hits']})..."
                        )

                        for i in range(0, len(api_list), BATCH_SIZE):
                            batch_roles = api_list[i:i + BATCH_SIZE]
                            trans_results = ai_translator.batch_translate(
                                batch_roles,
                                mode=role_translation_mode,
                                title=item_title,
                                year=item_year
                            )

                            if isinstance(trans_results, list) and len(trans_results) == len(batch_roles):
                                trans_results = {
                                    batch_roles[j]: trans_results[j]
                                    for j in range(len(batch_roles))
                                }
                            elif not isinstance(trans_results, dict):
                                trans_results = {}

                            for k, v in trans_results.items():
                                if isinstance(v, (list, tuple, set)):
                                    v = next((x for x in v if isinstance(x, str) and x.strip()), None)

                                if not v:
                                    continue

                                v = str(v).strip()

                                if not utils.contains_chinese(v):
                                    continue

                                cleaned_v = utils.clean_character_name_static(v)
                                if not cleaned_v:
                                    continue

                                role_trans_map[k] = cleaned_v

                                if role_translation_mode != 'quality':
                                    db_manager.save_translation_to_db(cursor, k, cleaned_v, ai_translator.provider)

                            import time
                            time.sleep(1)

        # 回填翻译结果到 JSON 树
        if person_trans_map or role_trans_map:

            def _apply_person_trans(data_dict):
                credits_data = data_dict.get('credits') or data_dict.get('aggregate_credits') or data_dict.get('casts') or {}

                # 替换导演
                for crew_member in credits_data.get('crew', []):
                    if crew_member.get('job') in ['Director', 'Series Director']:
                        name = crew_member.get('name')
                        if name in person_trans_map:
                            crew_member['original_name'] = name
                            crew_member['name'] = person_trans_map[name]

                # 替换主创
                for creator in data_dict.get('created_by', []):
                    name = creator.get('name')
                    if name in person_trans_map:
                        creator['original_name'] = name
                        creator['name'] = person_trans_map[name]

                # 替换演员和客串
                all_actors = credits_data.get('cast', []) + credits_data.get('guest_stars', [])
                for actor in all_actors:
                    name = actor.get('name')
                    if name in person_trans_map:
                        actor['original_name'] = name
                        actor['name'] = person_trans_map[name]

                    character = actor.get('character')
                    if character:
                        cleaned_char = utils.clean_character_name_static(character)
                        if cleaned_char in role_trans_map:
                            actor['character'] = utils.clean_character_name_static(role_trans_map[cleaned_char])

            if item_type == 'Movie':
                _apply_person_trans(tmdb_data)

            elif item_type == 'Series':
                _apply_person_trans(tmdb_data.get('series_details', tmdb_data))

                for season in tmdb_data.get("seasons_details", []):
                    _apply_person_trans(season)

                episodes_container = tmdb_data.get("episodes_details", {})
                episodes_list = episodes_container.values() if isinstance(episodes_container, dict) else episodes_container
                for ep in episodes_list:
                    _apply_person_trans(ep)

            translated_count += len(person_trans_map) + len(role_trans_map)

    # --- 4. 统计汇总日志 ---
    total_pending = (
        stats['title_pending_count'] +
        stats['overview_pending_count'] +
        stats['tagline_pending_count'] +
        stats['person_pending_count'] +
        stats['role_pending_count']
    )

    total_cache = (
        stats['title_cache_hits'] +
        stats['overview_cache_hits'] +
        stats['tagline_cache_hits'] +
        stats['person_cache_hits'] +
        stats['role_cache_hits']
    )

    total_submit = (
        stats['title_needs_translation'] +
        stats['overview_needs_translation'] +
        stats['tagline_needs_translation'] +
        stats['person_ai_calls'] +
        stats['role_ai_calls']
    )

    logger.info("  ➜ [AI翻译引擎] 翻译统计汇总")
    logger.info(
        f"  ➜ 演员节点: 原始 {stats['original_cast_count']} 人 → "
        f"最终保留 {stats['truncated_cast_count']} 人（含剧/季/集）"
    )
    logger.info(
        f"  ➜ 待翻词条: 标题 {stats['title_pending_count']} | "
        f"简介 {stats['overview_pending_count']} | "
        f"标语 {stats['tagline_pending_count']} | "
        f"人名 {stats['person_pending_count']} | "
        f"角色 {stats['role_pending_count']}"
    )
    logger.info(
        f"  ➜ 缓存命中: 标题 {stats['title_cache_hits']} | "
        f"简介 {stats['overview_cache_hits']} | "
        f"标语 {stats['tagline_cache_hits']} | "
        f"人名 {stats['person_cache_hits']} | "
        f"角色 {stats['role_cache_hits']}"
    )
    logger.info(
        f"  ➜ 实际提交: 标题 {stats['title_needs_translation']} | "
        f"简介 {stats['overview_needs_translation']} | "
        f"标语 {stats['tagline_needs_translation']} | "
        f"人名 {stats['person_ai_calls']} | "
        f"角色 {stats['role_ai_calls']}"
    )
    
    # --- 5. 合集占坑入库 ---
    if collections_to_upsert:
        from database import tmdb_collection_db
        for coll in collections_to_upsert:
            try:
                c_name = coll.get('name', '')
                if c_name.endswith("合集"):
                    c_name = c_name[:-2] + "（系列）"
                    coll['name'] = c_name
                    
                tmdb_collection_db.upsert_native_collection({
                    'tmdb_collection_id': str(coll.get('id')),
                    'name': c_name,
                    'overview': coll.get('overview', ''),
                    'poster_path': coll.get('poster_path'),
                    'backdrop_path': coll.get('backdrop_path'),
                    'all_tmdb_ids': coll.get('all_tmdb_ids', []),
                    'emby_collection_id': None 
                })
                logger.debug(f"  ➜ [大一统翻译] 已将合集 '{c_name}' 的翻译结果及关联 ID 预占位写入数据库。")
            except Exception as e:
                logger.warning(f"  ➜ [大一统翻译] 合集预占位写入失败: {e}")
