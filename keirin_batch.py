import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from keirin_data_formatter import scrape_and_format

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

session = requests.Session()
session.headers.update(HEADERS)


def get_today_race_urls(date_str=None):
    """当日の全レースURLを取得"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y/%m/%d")
    url = f"https://keirin.kdreams.jp/racecard/{date_str}/"
    print(f"開催一覧取得: {url}")
    res = session.get(url, timeout=10)
    if res.status_code != 200:
        print(f"エラー: {res.status_code}")
        return {}
    soup = BeautifulSoup(res.content, "html.parser")
    race_urls = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "racedetail" in href:
            race_id = re.sub(r"\D", "", href)
            if race_id:
                race_urls[race_id] = href
    print(f"取得レース数: {len(race_urls)}")
    time.sleep(2)
    return race_urls


def run_batch(date_str=None, max_races=None, wait_sec=1.5):
    """
    当日の全レースを一括取得・整形
    date_str : "YYYY/MM/DD" 形式。Noneなら今日
    max_races: テスト用に上限を設定（Noneなら全件）
    wait_sec : リクエスト間隔（サーバー負荷配慮）
    """
    start_time = datetime.now()
    if date_str is None:
        date_str = datetime.now().strftime("%Y/%m/%d")

    print("=" * 60)
    print(f"競輪データ 一括取得バッチ")
    print(f"対象日: {date_str}")
    print(f"開始時刻: {start_time.strftime('%H:%M:%S')}")
    print("=" * 60)

    # 全レースURL取得
    race_urls = get_today_race_urls(date_str)
    if not race_urls:
        print("レースURLが取得できませんでした")
        return []

    # テスト用上限
    items = list(race_urls.items())
    if max_races:
        items = items[:max_races]
        print(f"※ テストモード: 最初の{max_races}レースのみ取得")

    total = len(items)
    results = []
    errors = []

    print(f"\n全{total}レースを取得開始...\n")

    for i, (race_id, race_path) in enumerate(items, 1):
        # フルURLを組み立て
        base = "https://keirin.kdreams.jp"
        race_url = base + race_path if race_path.startswith("/") else race_path

        # 競輪場名をURLから抽出
        m = re.search(r"/(\w+)/racedetail/", race_url)
        stadium = m.group(1) if m else "unknown"

        # 進捗表示
        elapsed = (datetime.now() - start_time).seconds
        remain = int((total - i) * wait_sec)
        print(f"[{i:3d}/{total}] {stadium} R{race_id[-4:]} | "
              f"経過:{elapsed}秒 残り約:{remain}秒", end=" ")

        try:
            formatted = scrape_and_format(race_url)
            if "error" in formatted:
                print(f"-> エラー: {formatted['error']}")
                errors.append({"race_id": race_id, "url": race_url, "error": formatted["error"]})
            else:
                entry_count = len(formatted.get("entries", []))
                result_count = len(formatted.get("results", []))
                line_count = len(formatted.get("lines", {}).get("line_detail", []))
                is_hit = formatted.get("prediction_meta", {}).get("is_honmei_hit")
                hit_str = "◎的中" if is_hit else ("×外れ" if is_hit is False else "未確定")
                print(f"-> 選手:{entry_count} 結果:{result_count} ライン:{line_count} {hit_str}")
                results.append(formatted)

        except Exception as e:
            print(f"-> 例外: {type(e).__name__}: {e}")
            errors.append({"race_id": race_id, "url": race_url, "error": str(e)})

        time.sleep(wait_sec)

    # サマリー
    end_time = datetime.now()
    elapsed_total = (end_time - start_time).seconds
    hit_count = sum(1 for r in results if r.get("prediction_meta", {}).get("is_honmei_hit") is True)
    miss_count = sum(1 for r in results if r.get("prediction_meta", {}).get("is_honmei_hit") is False)
    decided = hit_count + miss_count

    print("\n" + "=" * 60)
    print("【バッチ完了サマリー】")
    print("=" * 60)
    print(f"  取得成功  : {len(results)}/{total} レース")
    print(f"  エラー    : {len(errors)} レース")
    print(f"  所要時間  : {elapsed_total}秒（{elapsed_total//60}分{elapsed_total%60}秒）")
    if decided > 0:
        print(f"  本命的中率: {hit_count}/{decided} = {hit_count/decided*100:.1f}%")

    # 競輪場別集計
    stadium_summary = {}
    for r in results:
        s = r.get("race", {}).get("stadium_name", "unknown")
        if s not in stadium_summary:
            stadium_summary[s] = {"total": 0, "hit": 0, "miss": 0}
        stadium_summary[s]["total"] += 1
        is_hit = r.get("prediction_meta", {}).get("is_honmei_hit")
        if is_hit is True:
            stadium_summary[s]["hit"] += 1
        elif is_hit is False:
            stadium_summary[s]["miss"] += 1

    print("\n  競輪場別:")
    for st, data in sorted(stadium_summary.items()):
        decided = data["hit"] + data["miss"]
        rate = f"{data['hit']/decided*100:.0f}%" if decided > 0 else "-"
        print(f"    {st:12s}: {data['total']}R 的中率{rate}")

    # JSON保存
    output = {
        "date": date_str,
        "scraped_at": end_time.isoformat(),
        "total_races": total,
        "success_count": len(results),
        "error_count": len(errors),
        "hit_rate": round(hit_count / decided, 3) if decided > 0 else None,
        "races": results,
        "errors": errors,
    }
    filename = f"batch_{date_str.replace('/', '')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n結果を {filename} に保存しました")

    return results


if __name__ == "__main__":
    import sys

    # 引数でテストモード切り替え
    # python keirin_batch.py         → 当日全レース
    # python keirin_batch.py test    → 最初の3レースのみ
    # python keirin_batch.py 2026/06/10  → 指定日
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "test":
            run_batch(max_races=3)
        else:
            run_batch(date_str=arg)
    else:
        run_batch()
