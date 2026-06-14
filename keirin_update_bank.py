import requests
from collections import defaultdict

SUPABASE_URL = "https://bjxosmqlmssxvoddeyae.supabase.co"
SUPABASE_KEY = "sb_publishable_HUOYksS-WVa6aXuyZCsflg_ZkmThDcK"
H = {"apikey": SUPABASE_KEY, "Authorization": "Bearer " + SUPABASE_KEY}
PATCH_H = {**H, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}

# 全レース結果を取得
print("データ取得中...")
results = []
offset = 0
while True:
    res = requests.get(
        SUPABASE_URL + f"/rest/v1/race_results?select=race_id,rank,kimete&limit=1000&offset={offset}",
        headers=H
    )
    data = res.json()
    if not data: break
    results.extend(data)
    offset += 1000
    if len(data) < 1000: break

races = []
offset = 0
while True:
    res = requests.get(
        SUPABASE_URL + f"/rest/v1/races?select=race_id,stadium_code&limit=1000&offset={offset}",
        headers=H
    )
    data = res.json()
    if not data: break
    races.extend(data)
    offset += 1000
    if len(data) < 1000: break

race_to_stadium = {r["race_id"]: r["stadium_code"] for r in races}

# 競輪場別集計
stadium_kimete = defaultdict(lambda: defaultdict(int))
stadium_total  = defaultdict(int)

for r in results:
    if r["rank"] != 1: continue
    stadium = race_to_stadium.get(r["race_id"], "")
    if not stadium: continue
    kimete = r.get("kimete", "") or ""
    stadium_kimete[stadium][kimete] += 1
    stadium_total[stadium] += 1

# bank_statsに保存
print("\nbank_statsに保存中...")
saved = 0
for stadium, total in stadium_total.items():
    if total < 10: continue
    nige   = stadium_kimete[stadium].get("逃", 0)
    makuri = stadium_kimete[stadium].get("捲", 0)
    sashi  = stadium_kimete[stadium].get("差", 0)
    record = {
        "stadium_code": stadium,
        "nige_rate":    round(nige / total, 4),
        "makuri_rate":  round(makuri / total, 4),
        "sashi_rate":   round(sashi / total, 4),
        "total_races":  total,
    }
    res = requests.post(
        SUPABASE_URL + "/rest/v1/bank_stats?on_conflict=stadium_code",
        headers=PATCH_H,
        json=[record],
        timeout=15
    )
    if res.status_code in [200, 201, 204]:
        saved += 1
        print(f"  {stadium:15} 逃:{nige/total*100:.1f}% 捲:{makuri/total*100:.1f}% 差:{sashi/total*100:.1f}%")
    else:
        print(f"  {stadium} ERROR: {res.text[:100]}")

print(f"\n完了: {saved}件保存")