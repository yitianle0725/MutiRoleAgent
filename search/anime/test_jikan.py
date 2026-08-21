from __future__ import annotations
import time
from typing import Any
from datetime import datetime, timezone

# 全部依赖从search_jikan导入，test脚本不实现底层逻辑
from search_jikan import (
    jikan_anime,
    jikan_characters,
    jikan_clubs,
    jikan_genres,
    jikan_magazines,
    jikan_manga,
    jikan_people,
    jikan_producers,
    jikan_random,
    jikan_recommendations,
    jikan_reviews,
    jikan_schedules,
    jikan_seasons,
    jikan_top,
    jikan_watch,
    save_results,
    SAVE_DIR,
)

SAFE_DELAY = 2.0


def test_01_anime() -> None:
    """#1 anime 全部子接口测试"""
    out_file = SAVE_DIR / "test_anime.json"
    results: dict[str, Any] = {}
    test_aid = 1
    tasks = [
        ("list", None, None, "anime_list"),
        ("info", test_aid, None, "anime_info"),
        ("full", test_aid, None, "anime_full"),
        ("characters", test_aid, None, "anime_characters"),
        ("staff", test_aid, None, "anime_staff"),
        ("episodes", test_aid, None, "anime_episodes"),
        ("single_episode", test_aid, 1, "anime_single_episode_1"),
        ("news", test_aid, None, "anime_news"),
        ("forum", test_aid, None, "anime_forum"),
        ("videos", test_aid, None, "anime_videos"),
        ("video_episodes", test_aid, None, "anime_video_episodes"),
        ("pictures", test_aid, None, "anime_pictures"),
        ("statistics", test_aid, None, "anime_statistics"),
        ("moreinfo", test_aid, None, "anime_moreinfo"),
        ("recommendations", test_aid, None, "anime_recommendations"),
        ("userupdates", test_aid, None, "anime_userupdates"),
        ("reviews", test_aid, None, "anime_reviews"),
        ("relations", test_aid, None, "anime_relations"),
        ("themes", test_aid, None, "anime_themes"),
        ("external", test_aid, None, "anime_external"),
        ("streaming", test_aid, None, "anime_streaming"),
    ]
    for mode, aid, ep, key_name in tasks:
        print(f"\n[Anime] mode={mode}, aid={aid}, ep={ep}")
        try:
            res = jikan_anime(mode, anime_id=aid, episode=ep)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 anime 完成, saved -> {out_file.resolve()}")


def test_02_characters() -> None:
    """#2 characters 全部子接口测试"""
    out_file = SAVE_DIR / "test_characters.json"
    results: dict[str, Any] = {}
    test_cid = 1
    tasks = [
        ("list", None, "characters_list"),
        ("info", test_cid, "characters_info"),
        ("full", test_cid, "characters_full"),
        ("anime", test_cid, "characters_anime"),
        ("manga", test_cid, "characters_manga"),
        ("voices", test_cid, "characters_voices"),
        ("pictures", test_cid, "characters_pictures"),
    ]
    for mode, cid, key_name in tasks:
        print(f"\n[Characters] mode={mode}, cid={cid}")
        try:
            if cid is not None:
                res = jikan_characters(mode, char_id=cid)
            else:
                res = jikan_characters(mode)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 characters 完成, saved -> {out_file.resolve()}")


def test_03_clubs() -> None:
    """#3 clubs 全部子接口测试"""
    out_file = SAVE_DIR / "test_clubs.json"
    results: dict[str, Any] = {}
    test_club_id = 1
    tasks = [
        ("list", None, "clubs_list"),
        ("info", test_club_id, "clubs_info"),
        ("members", test_club_id, "clubs_members"),
        ("staff", test_club_id, "clubs_staff"),
        ("relations", test_club_id, "clubs_relations"),
    ]
    for mode, cid, key_name in tasks:
        print(f"\n[Clubs] mode={mode}, cid={cid}")
        try:
            if cid is not None:
                res = jikan_clubs(mode, club_id=cid)
            else:
                res = jikan_clubs(mode)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 clubs 完成, saved -> {out_file.resolve()}")


def test_04_genres() -> None:
    """#4 genres 全部子接口测试"""
    out_file = SAVE_DIR / "test_genres.json"
    results: dict[str, Any] = {}
    task_list = [
        ("anime", None, "genres_anime_all"),
        ("anime", "genres", "genres_anime_genres"),
        ("anime", "explicit_genres", "genres_anime_explicit"),
        ("anime", "themes", "genres_anime_themes"),
        ("anime", "demographics", "genres_anime_demographics"),
        ("manga", None, "genres_manga_all"),
        ("manga", "genres", "genres_manga_genres"),
        ("manga", "explicit_genres", "genres_manga_explicit"),
        ("manga", "themes", "genres_manga_themes"),
        ("manga", "demographics", "genres_manga_demographics"),
    ]
    for media, flt, key_name in task_list:
        print(f"\n[Genres] media={media}, filter={flt}")
        try:
            res = jikan_genres(media, filter_type=flt)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 genres 完成, saved -> {out_file.resolve()}")


def test_05_magazines() -> None:
    """#5 magazines 接口测试"""
    out_file = SAVE_DIR / "test_magazines.json"
    results: dict[str, Any] = {}
    print("\n[Magazines] magazines list page1")
    try:
        res = jikan_magazines(page=1, limit=5)
        results["magazines_page1"] = res
        print("✅ magazines_page1 ok")
    except Exception as e:
        err_msg = str(e)
        print(f"❌ magazines_page1 fail: {err_msg}")
        results["magazines_page1"] = {"error": err_msg}
    time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 magazines 完成, saved -> {out_file.resolve()}")


def test_06_manga() -> None:
    """#6 manga 全部子接口测试"""
    out_file = SAVE_DIR / "test_manga.json"
    results: dict[str, Any] = {}
    test_mid = 1
    tasks = [
        ("list", None, "manga_list"),
        ("info", test_mid, "manga_info"),
        ("full", test_mid, "manga_full"),
        ("characters", test_mid, "manga_characters"),
        ("news", test_mid, "manga_news"),
        ("forum", test_mid, "manga_forum"),
        ("pictures", test_mid, "manga_pictures"),
        ("statistics", test_mid, "manga_statistics"),
        ("moreinfo", test_mid, "manga_moreinfo"),
        ("recommendations", test_mid, "manga_recommendations"),
        ("userupdates", test_mid, "manga_userupdates"),
        ("reviews", test_mid, "manga_reviews"),
        ("relations", test_mid, "manga_relations"),
        ("external", test_mid, "manga_external"),
    ]
    for mode, mid, key_name in tasks:
        print(f"\n[Manga] mode={mode}, mid={mid}")
        try:
            if mid is not None:
                res = jikan_manga(mode, manga_id=mid)
            else:
                res = jikan_manga(mode)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 manga 完成, saved -> {out_file.resolve()}")


def test_07_people() -> None:
    """#7 people 全部子接口测试"""
    out_file = SAVE_DIR / "test_people.json"
    results: dict[str, Any] = {}
    test_pid = 1
    tasks = [
        ("list", None, "people_list"),
        ("info", test_pid, "people_info"),
        ("full", test_pid, "people_full"),
        ("anime", test_pid, "people_anime"),
        ("voices", test_pid, "people_voices"),
        ("manga", test_pid, "people_manga"),
        ("pictures", test_pid, "people_pictures"),
    ]
    for mode, pid, key_name in tasks:
        print(f"\n[People] mode={mode}, pid={pid}")
        try:
            if pid is not None:
                res = jikan_people(mode, person_id=pid)
            else:
                res = jikan_people(mode)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 people 完成, saved -> {out_file.resolve()}")


def test_08_producers() -> None:
    """#8 producers 全部子接口测试"""
    out_file = SAVE_DIR / "test_producers.json"
    results: dict[str, Any] = {}
    test_pid = 1
    tasks = [
        ("list", None, "producers_list"),
        ("info", test_pid, "producers_info"),
        ("full", test_pid, "producers_full"),
        ("external", test_pid, "producers_external"),
    ]
    for mode, pid, key_name in tasks:
        print(f"\n[Producers] mode={mode}, pid={pid}")
        try:
            if pid is not None:
                res = jikan_producers(mode, producer_id=pid)
            else:
                res = jikan_producers(mode)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 producers 完成, saved -> {out_file.resolve()}")


def test_09_random() -> None:
    """#9 random 全部子接口测试"""
    out_file = SAVE_DIR / "test_random.json"
    results: dict[str, Any] = {}
    task_list = [
        ("anime", "random_anime"),
        ("manga", "random_manga"),
        ("characters", "random_characters"),
        ("people", "random_people"),
        ("users", "random_users"),
    ]
    for rtype, key_name in task_list:
        print(f"\n[Random] type={rtype}")
        try:
            res = jikan_random(rtype)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 random 完成, saved -> {out_file.resolve()}")


def test_10_recommendations() -> None:
    """#10 recommendations 全部子接口测试"""
    out_file = SAVE_DIR / "test_recommendations.json"
    results: dict[str, Any] = {}
    task_list = [
        ("anime", "rec_anime"),
        ("manga", "rec_manga"),
    ]
    for rtype, key_name in task_list:
        print(f"\n[Recommendations] type={rtype}")
        try:
            res = jikan_recommendations(rtype)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 recommendations 完成, saved -> {out_file.resolve()}")


def test_11_reviews() -> None:
    """#11 reviews 全部子接口测试"""
    out_file = SAVE_DIR / "test_reviews.json"
    results: dict[str, Any] = {}
    task_list = [
        ("anime", "reviews_anime"),
        ("manga", "reviews_manga"),
    ]
    for rtype, key_name in task_list:
        print(f"\n[Reviews] type={rtype}")
        try:
            res = jikan_reviews(rtype)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 reviews 完成, saved -> {out_file.resolve()}")


def test_12_schedules() -> None:
    """#12 schedules"""
    out_file = SAVE_DIR / "test_schedules.json"
    results: dict[str, Any] = {}
    print("\n[Schedules] schedules")
    try:
        res = jikan_schedules()
        results["schedules"] = res
        print("✅ schedules ok")
    except Exception as e:
        err_msg = str(e)
        print(f"❌ schedules fail: {err_msg}")
        results["schedules"] = {"error": err_msg}
    time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 schedules 完成, saved -> {out_file.resolve()}")


def test_13_seasons() -> None:
    """#13 seasons 全部子接口测试"""
    out_file = SAVE_DIR / "test_seasons.json"
    results: dict[str, Any] = {}
    task_list = [
        ("now", None, None, "seasons_now"),
        ("upcoming", None, None, "seasons_upcoming"),
        ("list", None, None, "seasons_list"),
        ("year+season", 2025, "winter", "seasons_2025_winter"),
    ]
    for op, year, season, key_name in task_list:
        print(f"\n[Seasons] op={op}, year={year}, season={season}")
        try:
            res = jikan_seasons(op, year=year, season=season)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 seasons 完成, saved -> {out_file.resolve()}")


def test_14_top() -> None:
    """#14 top 全部子接口测试"""
    out_file = SAVE_DIR / "test_top.json"
    results: dict[str, Any] = {}
    task_list = [
        ("anime", "top_anime"),
        ("manga", "top_manga"),
        ("people", "top_people"),
        ("characters", "top_characters"),
        ("reviews", "top_reviews"),
    ]
    for ttype, key_name in task_list:
        print(f"\n[Top] type={ttype}")
        try:
            res = jikan_top(ttype)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 top 完成, saved -> {out_file.resolve()}")


def test_15_watch() -> None:
    """#15 watch 全部4个子接口测试"""
    out_file = SAVE_DIR / "test_watch.json"
    results: dict[str, Any] = {}
    task_list = [
        ("recent_episodes", "watch_recent_episodes"),
        ("popular_episodes", "watch_popular_episodes"),
        ("recent_promos", "watch_recent_promos"),
        ("popular_promos", "watch_popular_promos"),
    ]
    for wtype, key_name in task_list:
        print(f"\n[Watch] type={wtype}")
        try:
            res = jikan_watch(wtype)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(SAFE_DELAY)
    save_results(results, out_file)
    print(f"\n🏁 watch 完成, saved -> {out_file.resolve()}")


def run_all_15_tests():
    """一键串行跑全部15个顶层资源，保守不并发"""
    test_funcs = [
        test_01_anime,
        test_02_characters,
        test_03_clubs,
        test_04_genres,
        test_05_magazines,
        test_06_manga,
        test_07_people,
        test_08_producers,
        test_09_random,
        test_10_recommendations,
        test_11_reviews,
        test_12_schedules,
        test_13_seasons,
        test_14_top,
        test_15_watch,
    ]
    for fn in test_funcs:
        fn()


from datetime import datetime, timezone

def run_check_all_status() -> None:
    """
    仅做接口可用性巡检，输出 api_check_status.json
    不输出各个原始大json，只记录每个接口 ok / error 状态
    """
    out_status_file = SAVE_DIR / "api_check_status.json"
    check_result: dict[str, Any] = {
        "check_at": datetime.now(timezone.utc).isoformat(),
        "items": {}
    }

    # ========== 全部接口清单，key:唯一标识，(调用函数, 参数元组) ==========
    check_tasks = [
        # ===== 01 anime =====
        ("anime‑anime_list",        (jikan_anime, ("list", None, None))),
        ("anime‑anime_info",        (jikan_anime, ("info", 1, None))),
        ("anime‑anime_full",        (jikan_anime, ("full", 1, None))),
        ("anime‑anime_characters",  (jikan_anime, ("characters", 1, None))),
        ("anime‑anime_staff",       (jikan_anime, ("staff", 1, None))),
        ("anime‑anime_episodes",    (jikan_anime, ("episodes", 1, None))),
        ("anime‑anime_single_episode_1", (jikan_anime, ("single_episode", 1, 1))),
        ("anime‑anime_news",        (jikan_anime, ("news", 1, None))),
        ("anime‑anime_forum",       (jikan_anime, ("forum", 1, None))),
        ("anime‑anime_videos",      (jikan_anime, ("videos", 1, None))),
        ("anime‑anime_video_episodes", (jikan_anime, ("video_episodes",1,None))),
        ("anime‑anime_pictures",    (jikan_anime, ("pictures",1, None))),
        ("anime‑anime_statistics",  (jikan_anime, ("statistics",1, None))),
        ("anime‑anime_moreinfo",    (jikan_anime, ("moreinfo",1, None))),
        ("anime‑anime_recommendations", (jikan_anime, ("recommendations",1,None))),
        ("anime‑anime_userupdates", (jikan_anime, ("userupdates",1, None))),
        ("anime‑anime_reviews",     (jikan_anime, ("reviews",1, None))),
        ("anime‑anime_relations",   (jikan_anime, ("relations",1, None))),
        ("anime‑anime_themes",      (jikan_anime, ("themes",1, None))),
        ("anime‑anime_external",    (jikan_anime, ("external",1, None))),
        ("anime‑anime_streaming",   (jikan_anime, ("streaming",1, None))),

        # =====02 characters =====
        ("characters‑list",          (jikan_characters, ("list", None))),
        ("characters‑info",          (jikan_characters, ("info", 1))),
        ("characters‑full",          (jikan_characters, ("full", 1))),
        ("characters‑anime",         (jikan_characters, ("anime", 1))),
        ("characters‑manga",         (jikan_characters, ("manga", 1))),
        ("characters‑voices",        (jikan_characters, ("voices", 1))),
        ("characters‑pictures",      (jikan_characters, ("pictures", 1))),

        # =====03 clubs =====
        ("clubs‑list",               (jikan_clubs, ("list", None))),
        ("clubs‑info",               (jikan_clubs, ("info", 1))),
        ("clubs‑members",            (jikan_clubs, ("members", 1))),
        ("clubs‑staff",              (jikan_clubs, ("staff", 1))),
        ("clubs‑relations",          (jikan_clubs, ("relations", 1))),

        # =====04 genres =====
        ("genres‑anime_all",         (jikan_genres, ("anime", None))),
        ("genres‑anime_genres",      (jikan_genres, ("anime", "genres"))),
        ("genres‑anime_explicit",    (jikan_genres, ("anime", "explicit_genres"))),
        ("genres‑anime_themes",      (jikan_genres, ("anime", "themes"))),
        ("genres‑anime_demographics",(jikan_genres, ("anime", "demographics"))),
        ("genres‑manga_all",         (jikan_genres, ("manga", None))),
        ("genres‑manga_genres",      (jikan_genres, ("manga", "genres"))),
        ("genres‑manga_explicit",    (jikan_genres, ("manga", "explicit_genres"))),
        ("genres‑manga_themes",      (jikan_genres, ("manga", "themes"))),
        ("genres‑manga_demographics",(jikan_genres,("manga","demographics"))),

        # =====05 magazines =====
        ("magazines‑page1",          (jikan_magazines, (1,5,None,None,None,None))),

        # =====06 manga =====
        ("manga‑list",               (jikan_manga, ("list", None))),
        ("manga‑info",               (jikan_manga, ("info", 1))),
        ("manga‑full",               (jikan_manga, ("full", 1))),
        ("manga‑characters",         (jikan_manga, ("characters",1))),
        ("manga‑news",               (jikan_manga, ("news",1))),
        ("manga‑forum",              (jikan_manga, ("forum",1))),
        ("manga‑pictures",           (jikan_manga, ("pictures",1))),
        ("manga‑statistics",         (jikan_manga, ("statistics",1))),
        ("manga‑moreinfo",           (jikan_manga, ("moreinfo",1))),
        ("manga‑recommendations",    (jikan_manga, ("recommendations",1))),
        ("manga‑userupdates",        (jikan_manga, ("userupdates",1))),
        ("manga‑reviews",            (jikan_manga, ("reviews",1))),
        ("manga‑relations",          (jikan_manga, ("relations",1))),
        ("manga‑external",           (jikan_manga, ("external",1))),

        # =====07 people =====
        ("people‑list",              (jikan_people, ("list", None))),
        ("people‑info",              (jikan_people, ("info", 1))),
        ("people‑full",              (jikan_people, ("full", 1))),
        ("people‑anime",             (jikan_people, ("anime",1))),
        ("people‑voices",            (jikan_people, ("voices",1))),
        ("people‑manga",              (jikan_people, ("manga",1))),
        ("people‑pictures",          (jikan_people, ("pictures",1))),

        # =====08 producers =====
        ("producers‑list",           (jikan_producers, ("list", None))),
        ("producers‑info",           (jikan_producers, ("info",1))),
        ("producers‑full",           (jikan_producers, ("full",1))),
        ("producers‑external",       (jikan_producers, ("external",1))),

        # =====09 random =====
        ("random‑anime",             (jikan_random, ("anime",))),
        ("random‑manga",             (jikan_random, ("manga",))),
        ("random‑characters",        (jikan_random, ("characters",))),
        ("random‑people",             (jikan_random, ("people",))),
        ("random‑users",              (jikan_random, ("users",))),

        # =====10 recommendations =====
        ("recommendations‑anime",    (jikan_recommendations, ("anime",))),
        ("recommendations‑manga",    (jikan_recommendations, ("manga",))),

        # =====11 reviews =====
        ("reviews‑anime",            (jikan_reviews, ("anime",))),
        ("reviews‑manga",             (jikan_reviews, ("manga",))),

        # =====12 schedules =====
        ("schedules‑main",           (jikan_schedules, ())),

        # =====13 seasons =====
        ("seasons‑now",              (jikan_seasons, ("now", None, None))),
        ("seasons‑upcoming",         (jikan_seasons, ("upcoming", None, None))),
        ("seasons‑list",             (jikan_seasons, ("list", None, None))),
        ("seasons‑2025_winter",       (jikan_seasons, ("year+season",2025,"winter"))),

        # =====14 top =====
        ("top‑anime",                (jikan_top, ("anime",))),
        ("top‑manga",                (jikan_top, ("manga",))),
        ("top‑people",               (jikan_top, ("people",))),
        ("top‑characters",           (jikan_top, ("characters",))),
        ("top‑reviews",              (jikan_top, ("reviews",))),

        # =====15 watch =====
        ("watch‑recent_episodes",    (jikan_watch, ("recent_episodes",))),
        ("watch‑popular_episodes",  (jikan_watch, ("popular_episodes",))),
        ("watch‑recent_promos",     (jikan_watch, ("recent_promos",))),
        ("watch‑popular_promos",    (jikan_watch, ("popular_promos",))),
    ]

    for item_key, (func, args_tuple) in check_tasks:
        print(f"\n🔍 checking: {item_key}")
        try:
            _ = func(*args_tuple)
            check_result["items"][item_key] = {
                "status": "ok",
                "error_msg": ""
            }
            print(f"✅ {item_key} ok")
        except Exception as e:
            err_text = str(e)
            check_result["items"][item_key] = {
                "status": "error",
                "error_msg": err_text
            }
            print(f"❌ {item_key} error: {err_text}")
        time.sleep(SAFE_DELAY)

    save_results(check_result, out_status_file)
    print(f"\n📋 接口状态巡检完成，输出：{out_status_file.resolve()}")


if __name__ == "__main__":
    # 1. 全部原始数据导出
    # run_all_15_tests()

    # 2. 只做可用性巡检，输出 api_check_status.json
    run_check_all_status()

    # 单个调试
    # test_15_watch()
    pass
