import json
import re
import requests
from datetime import datetime

SUPABASE_URL = "https://bjxosmqlmssxvoddeyae.supabase.co"
SUPABASE_KEY = "sb_publishable_HUOYksS-WVa6aXuyZCsflg_ZkmThDcK"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

def upsert(table, data):
    """Supabaseにupsert（重複時は更新）"""
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
        json=data if isinstance(data, list) else [data],
        timeout=15
    )
    return res.status_code in [200, 201]

def extract_race_date(race_id):
    """レースIDから日付を抽出（例: 1220260610020001 → 2026-06-10）"""
    m = re.search(r"(\d{4})(\d{2})(\d{2})", race_id[2:10])
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None

def save_race(race_data):
    """racesテーブルに保存"""
    race_id = race_data["race"]["race_id"]
    record = {
        "race_id":      race_id,
        "stadium_code": race_data["race"]["stadium_name"],
        "race_date":    extract_race_date(race_id),
        "scraped_at":   race_data["race"]["scraped_at"],
        "player_count": race_data["race"]["player_count"],
    }
    return upsert("races", record)

def save_entries(race_data):
    """race_entriesテーブルに保存"""
    race_id = race_data["race"]["race_id"]
    records = []
    for p in race_data.get("entries", []):
        records.append({
            "race_id":               race_id,
            "car_no":                p["car_no"],
            "frame_no":              p["frame_no"],
            "player_name":           p["name"],
            "prefecture":            p["prefecture"],
            "age":                   p["age"],
            "period":                p["period"],
            "grade":                 p["grade"],
            "leg_type":              p["leg_type"],
            "gear_ratio":            p["gear_ratio"],
            "current_score":         p["current_score"],
            "comment":               p["comment"],
            "yoso_mark":             p["yoso_mark"],
            "yoso_rank":             p["yoso_rank"],
            "stadium_wins_year":     p.get("stadium_wins_year"),
            "last5years_at_stadium": p.get("last5years_at_stadium", 0),
            "recent_this_venue":     p.get("recent_this_venue", ""),
            "recent_last_venue":     p.get("recent_last_venue", ""),
            "recent_2nd_last_venue": p.get("recent_2nd_last_venue", ""),
        })
    if not records:
        return True
    return upsert("race_entries", records)

def save_results(race_data):
    """race_resultsテーブルに保存"""
    race_id = race_data["race"]["race_id"]
    records = []
    for r in race_data.get("results", []):
        records.append({
            "race_id":        race_id,
            "rank":           r["rank"],
            "car_no":         r["car_no"],
            "player_name":    r["player_name"],
            "finish_gap":     r["finish_gap"],
            "last_lap_time":  r["last_lap_time"],
            "kimete":         r["kimete"],
            "sb_flag":        r["sb_flag"],
            "yoso_mark":      r["yoso_mark"],
        })
    if not records:
        return True
    return upsert("race_results", records)

def save_lines(race_data):
    """race_linesテーブルに保存"""
    race_id = race_data["race"]["race_id"]
    records = []
    for line in race_data.get("lines", {}).get("line_detail", []):
        records.append({
            "race_id":    race_id,
            "line_no":    line["line_no"],
            "cars":       "-".join(map(str, line["cars"])),
            "names":      " - ".join(line["names"]),
            "leader_car": line["leader_car"],
        })
    if not records:
        return True
    return upsert("race_lines", records)

def save_prediction(race_data):
    """ai_predictionsテーブルに保存"""
    meta = race_data.get("prediction_meta", {})
    if not meta.get("honmei_car"):
        return True
    record = {
        "race_id":       race_data["race"]["race_id"],
        "honmei_car":    meta["honmei_car"],
        "honmei_name":   meta["honmei_name"],
        "is_honmei_hit": meta["is_honmei_hit"],
    }
    return upsert("ai_predictions", record)

def save_batch(batch_file):
    """batchファイルを読み込んでSupabaseに全件保存"""
    with open(batch_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    races = data.get("races", [])
    total = len(races)
    success = 0
    errors = []

    print(f"保存開始: {batch_file}")
    print(f"対象レース数: {total}")
    print()

    for i, race_data in enumerate(races, 1):
        race_id = race_data["race"]["race_id"]
        stadium = race_data["race"]["stadium_name"]
        print(f"[{i:3d}/{total}] {stadium} {race_id[-4:]}", end=" ")

        ok = True
        ok = ok and save_race(race_data)
        ok = ok and save_entries(race_data)
        ok = ok and save_results(race_data)
        ok = ok and save_lines(race_data)
        ok = ok and save_prediction(race_data)

        if ok:
            success += 1
            print("-> OK")
        else:
            errors.append(race_id)
            print("-> ERROR")

    print()
    print("=" * 50)
    print(f"完了: {success}/{total} 件保存成功")
    if errors:
        print(f"エラー: {errors}")

if __name__ == "__main__":
    import sys
    import os
    # 引数でファイル指定、なければ最新のbatchファイルを使用
    if len(sys.argv) > 1:
        batch_file = sys.argv[1]
    else:
        # 最新のbatch_*.jsonを探す
        files = sorted([f for f in os.listdir(".") if f.startswith("batch_") and f.endswith(".json")])
        if not files:
            print("batch_*.jsonが見つかりません")
            sys.exit(1)
        batch_file = files[-1]
        print(f"最新バッチファイルを使用: {batch_file}")

    save_batch(batch_file)