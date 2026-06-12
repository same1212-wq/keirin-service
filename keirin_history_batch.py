import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from keirin_data_formatter import scrape_and_format
from keirin_supabase_save import save_batch

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

session = requests.Session()
session.headers.update(HEADERS)

def get_race_urls_for_date(date_str):
    """指定日のレースURL一覧を取得"""
    url = f"https://keirin.kdreams.jp/racecard/{date_str}/"
    try:
        res = session.get(url, timeout=15)
        if res.status_code != 200:
            return {}
        soup = BeautifulSoup(res.content, "html.parser")
        race_urls = {}
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "racedetail" in href:
                race_id = re.sub(r"\D", "", href)
                if race_id:
                    race_urls[race_id] = href
        return race_urls
    except Exception as e:
        print(f"  エラー: {e}")
        return {}

def run_history_batch(days=30, wait_sec=2.0):
    """過去N日分を一括取得してSupabaseに保存"""
    today = datetime.now()
    total_success = 0
    total_error = 0
    total_races = 0

    print("=" * 60)
    print(f"過去{days}日分 一括取得バッチ")
    print(f"開始時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    for day_offset in range(1, days + 1):
        target_date = today - timedelta(days=day_offset)
        date_str = target_date.strftime("%Y/%m/%d")
        date_label = target_date.strftime("%Y-%m-%d")

        print(f"\n【{day_offset}/{days}日目】{date_label} 取得中...")

        # レースURL取得
        race_urls = get_race_urls_for_date(date_str)
        if not race_urls:
            print(f"  レースなし or エラー → スキップ")
            time.sleep(2)
            continue

        print(f"  レース数: {len(race_urls)}")

        # 各レースのデータ取得
        results = []
        errors = []
        items = list(race_urls.items())

        for i, (race_id, race_path) in enumerate(items, 1):
            base = "https://keirin.kdreams.jp"
            race_url = base + race_path if race_path.startswith("/") else race_path
            m = re.search(r"/(\w+)/racedetail/", race_url)
            stadium = m.group(1) if m else "unknown"

            print(f"  [{i:3d}/{len(items)}] {stadium} {race_id[-4:]}", end=" ")

            try:
                formatted = scrape_and_format(race_url)
                if "error" in formatted:
                    print(f"-> エラー: {formatted['error']}")
                    errors.append(race_id)
                else:
                    entry_count = len(formatted.get("entries", []))
                    result_count = len(formatted.get("results", []))
                    print(f"-> 選手:{entry_count} 結果:{result_count}")
                    results.append(formatted)
            except Exception as e:
                print(f"-> 例外: {e}")
                errors.append(race_id)

            time.sleep(wait_sec)

        # 1日分をSupabaseに保存
        if results:
            batch_data = {
                "date": date_str,
                "scraped_at": datetime.now().isoformat(),
                "total_races": len(items),
                "success_count": len(results),
                "error_count": len(errors),
                "races": results,
                "errors": [{"race_id": r, "url": "", "error": "error"} for r in errors],
            }
            filename = f"batch_{target_date.strftime('%Y%m%d')}.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(batch_data, f, ensure_ascii=False, indent=2)

            print(f"\n  Supabaseに保存中...")
            save_batch(filename)

            total_success += len(results)
            total_error += len(errors)
            total_races += len(items)

        print(f"  本日小計: 成功{len(results)} / エラー{len(errors)}")

    # 最終サマリー
    print("\n" + "=" * 60)
    print("【全体サマリー】")
    print("=" * 60)
    print(f"  取得成功: {total_success}レース")
    print(f"  エラー  : {total_error}レース")
    print(f"  合計    : {total_races}レース")
    print(f"  完了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_history_batch(days=days)