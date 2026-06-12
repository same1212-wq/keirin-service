import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

PREFECTURES = {
    "\u5317\u6d77\u9053","\u9752\u68ee","\u5ca9\u624b","\u5bae\u57ce","\u79cb\u7530","\u5c71\u5f62","\u798f\u5cf6","\u8309\u57ce","\u6803\u6728","\u7fa4\u99ac",
    "\u57fc\u7389","\u5343\u8449","\u6771\u4eac","\u795e\u5948\u5ddd","\u65b0\u6f5f","\u5bcc\u5c71","\u77f3\u5ddd","\u798f\u4e95","\u5c71\u68a8","\u9577\u91ce",
    "\u5c90\u961c","\u9759\u5ca1","\u611b\u77e5","\u4e09\u91cd","\u6ecb\u8cc0","\u4eac\u90fd","\u5927\u962a","\u5175\u5eab","\u5948\u826f","\u548c\u6b4c\u5c71",
    "\u9ce5\u53d6","\u5cf6\u6839","\u5ca1\u5c71","\u5e83\u5cf6","\u5c71\u53e3","\u5fb3\u5cf6","\u9999\u5ddd","\u611b\u5a9b","\u9ad8\u77e5","\u798f\u5ca1",
    "\u4f50\u8cc0","\u9577\u5d0e","\u718a\u672c","\u5927\u5206","\u5bae\u5d0e","\u9e7f\u5150\u5cf6","\u6c96\u7e04"
}

YOSO_SCORE = {"\u25ce":1,"\u25cb":2,"\u25b3":3,"\u25b2":4,"\u6ce8":5,"\u00d7":6}

def col(cells, idx, default=""):
    return cells[idx] if idx < len(cells) else default

def is_shifted(cells):
    return len(cells) > 4 and not cells[4].isdigit()

def safe_float(val):
    m = re.search(r"[\d]+\.[\d]+|[\d]+", str(val))
    return float(m.group()) if m else 0.0

def parse_player_name(raw):
    parts = raw.split("/")
    if len(parts) != 3:
        return {"name": raw, "prefecture": "", "age": 0, "period": 0}
    name_pref_raw = parts[0]
    try:
        age = int(parts[1])
        period = int(parts[2])
    except ValueError:
        age, period = 0, 0
    zs_idx = name_pref_raw.find("\u3000")
    if zs_idx == -1:
        return {"name": name_pref_raw.strip(), "prefecture": "", "age": age, "period": period}
    before = name_pref_raw[:zs_idx]
    after = name_pref_raw[zs_idx+1:]
    tokens = before.split(" ")
    last_token = tokens[-1]
    for split_pos in range(1, min(4, len(last_token)+1)):
        pref_candidate = last_token[-split_pos:] + after
        if pref_candidate in PREFECTURES:
            name_last = last_token[:-split_pos]
            name_parts = tokens[:-1] + ([name_last] if name_last else [])
            return {"name": " ".join(name_parts).strip(), "prefecture": pref_candidate, "age": age, "period": period}
    return {"name": before.strip(), "prefecture": after, "age": age, "period": period}

def parse_line_groups(players):
    surname_to_car = {}
    for p in players:
        surname = p["name"].split(" ")[0] if " " in p["name"] else p["name"]
        surname_to_car[surname] = p["car_no"]
    follows = {}
    leaders = []
    solos = []
    for p in players:
        comment = p.get("comment", "")
        car_no = p["car_no"]
        if any(kw in comment for kw in ["\u5358\u9a0e","\uff11\u4eba\u3067","\u4e00\u4eba\u3067","\u5358\u72ec"]):
            solos.append(car_no)
        elif "\u81ea\u529b" in comment:
            leaders.append(car_no)
        else:
            match = re.match(r"^(.+?)(?:\u541b|\u3055\u3093)\u3002$", comment)
            if match:
                target_car = surname_to_car.get(match.group(1))
                if target_car:
                    follows[car_no] = target_car
    def build_line(start_car):
        line = [start_car]
        changed = True
        while changed:
            changed = False
            for car, fc in follows.items():
                if fc in line and car not in line:
                    line.append(car)
                    changed = True
        return line
    lines = [build_line(l) for l in leaders]
    car_to_name = {p["car_no"]: p["name"] for p in players}
    line_detail = [
        {"line_no": i+1, "cars": line,
         "names": [car_to_name.get(c,"") for c in line],
         "leader_car": line[0]}
        for i, line in enumerate(lines)
    ]
    return {"lines": lines, "solo": solos, "line_detail": line_detail, "follows_map": follows}

def parse_player_table_by_index(soup):
    players = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
        if "\u9078\u624b\u30b3\u30e1\u30f3\u30c8" not in header_cells:
            continue
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
            if len(cells) < 8:
                continue
            shifted = is_shifted(cells)
            car_no   = col(cells, 3) if shifted else col(cells, 4)
            name_raw = col(cells, 4) if shifted else col(cells, 5)
            grade    = col(cells, 5) if shifted else col(cells, 6)
            leg_type = col(cells, 6) if shifted else col(cells, 7)
            gear     = col(cells, 7) if shifted else col(cells, 8)
            score    = col(cells, 8) if shifted else col(cells, 9)
            comment  = col(cells, 9) if shifted else col(cells, 10)
            frame_no = col(cells, 3)
            yoso     = col(cells, 0)
            if not car_no.isdigit():
                continue
            if "/" not in name_raw:
                continue
            parsed = parse_player_name(name_raw)
            players.append({
                "car_no":        int(car_no),
                "frame_no":      int(frame_no) if frame_no.isdigit() else int(car_no),
                "yoso_mark":     yoso,
                "yoso_rank":     YOSO_SCORE.get(yoso, 99),
                "grade":         grade,
                "leg_type":      leg_type,
                "gear_ratio":    safe_float(gear),
                "current_score": safe_float(score),
                "comment":       comment,
                "name":          parsed["name"],
                "prefecture":    parsed["prefecture"],
                "age":           parsed["age"],
                "period":        parsed["period"],
                "stadium_wins_year": None,
                "last5years_at_stadium": 0,
                "recent_this_venue": "",
                "recent_last_venue": "",
                "recent_2nd_last_venue": "",
            })
    return players

def parse_stadium_stats_by_index(soup, players):
    car_to_stadium = {}
    car_to_gonen   = {}
    car_to_recent  = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
        header_str = " ".join(header_cells)
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
            if len(cells) < 4:
                continue
            shifted = is_shifted(cells)
            car_no = col(cells, 3) if shifted else col(cells, 4)
            if not car_no.isdigit():
                continue
            if "\u540c\u8d70\u8def\u5e74\u9593\u52dd\u5229\u5ea6\u6570" in header_str:
                wins = col(cells, 9) if shifted else col(cells, 10)
                car_to_stadium[car_no] = wins
            elif "\u5f53\u6240\uff15\u5e74" in header_str:
                val = col(cells, 9) if shifted else col(cells, 10)
                car_to_gonen[car_no] = val
            elif "\u524d\u5834\u6240\u6210\u7e3e" in header_str:
                car_to_recent[car_no] = {
                    "recent_this_venue":     col(cells, 3) if shifted else col(cells, 4),
                    "recent_last_venue":     col(cells, 4) if shifted else col(cells, 5),
                    "recent_2nd_last_venue": col(cells, 5) if shifted else col(cells, 6),
                }
    for p in players:
        car_str = str(p["car_no"])
        sw = car_to_stadium.get(car_str, "")
        p["stadium_wins_year"]       = int(sw) if sw.isdigit() else None
        p["last5years_at_stadium"]   = int(car_to_gonen.get(car_str, 0) or 0)
        recent = car_to_recent.get(car_str, {})
        p["recent_this_venue"]       = recent.get("recent_this_venue", "")
        p["recent_last_venue"]       = recent.get("recent_last_venue", "")
        p["recent_2nd_last_venue"]   = recent.get("recent_2nd_last_venue", "")
    return players

def extract_results_direct(soup):
    """テーブル構造から直接結果を取得（ヘッダーインデックス方式）"""
    results = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [h.get_text(strip=True) for h in rows[0].find_all(["th","td"])]
        if not all(h in headers for h in ["\u7740\u9806","\u8eca\u756a","\u9078\u624b\u540d"]):
            continue
        idx_rank   = headers.index("\u7740\u9806")
        idx_car    = headers.index("\u8eca\u756a")
        idx_name   = headers.index("\u9078\u624b\u540d")
        idx_gap    = headers.index("\u7740\u5dee") if "\u7740\u5dee" in headers else -1
        idx_time   = headers.index("\u4e0a\u308a") if "\u4e0a\u308a" in headers else -1
        idx_kimete = headers.index("\u6c7a\u307e\u308a\u624b") if "\u6c7a\u307e\u308a\u624b" in headers else -1
        idx_sb     = headers.index("S\uff0fB") if "S\uff0fB" in headers else -1
        idx_yoso   = headers.index("\u4e88\u60f3") if "\u4e88\u60f3" in headers else -1
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
            if len(cells) <= idx_rank:
                continue
            rank_val = cells[idx_rank]
            if not rank_val.isdigit():
                continue
            results.append({
                "rank":          int(rank_val),
                "car_no":        int(cells[idx_car]) if idx_car < len(cells) and cells[idx_car].isdigit() else 0,
                "player_name":   cells[idx_name] if idx_name < len(cells) else "",
                "finish_gap":    cells[idx_gap] if idx_gap >= 0 and idx_gap < len(cells) else "",
                "last_lap_time": safe_float(cells[idx_time]) if idx_time >= 0 and idx_time < len(cells) else 0,
                "kimete":        cells[idx_kimete] if idx_kimete >= 0 and idx_kimete < len(cells) else "",
                "sb_flag":       cells[idx_sb] if idx_sb >= 0 and idx_sb < len(cells) else "",
                "yoso_mark":     cells[idx_yoso] if idx_yoso >= 0 and idx_yoso < len(cells) else "",
            })
        if results:
            break
    results.sort(key=lambda x: x["rank"])
    return results

def extract_race_order(soup):
    """並び順をsoupから直接取得"""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [h.get_text(strip=True) for h in rows[0].find_all(["th","td"])]
        if "\u4e88\u60f3\u30fb\u5468\u56de\u30fb\u6226\u6cd5" not in headers:
            continue
        order_keys = ["\u25ce","\u25cb","\u25b3","\u6ce8","\u25b2","\u00d7"]
        for row in rows[1:2]:
            cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
            row_dict = dict(zip(headers, cells))
            predicted_order = [int(row_dict[k]) for k in order_keys if row_dict.get(k,"").isdigit()]
            return {"predicted_order": predicted_order}
    return {}

def scrape_and_format(race_url):
    import time
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        res = session.get(race_url, timeout=15)
    except Exception as e:
        return {"error": str(e)}
    if res.status_code != 200:
        return {"error": f"HTTP {res.status_code}"}
    soup = BeautifulSoup(res.content, "html.parser")
    players    = parse_player_table_by_index(soup)
    players    = parse_stadium_stats_by_index(soup, players)
    results    = extract_results_direct(soup)
    race_order = extract_race_order(soup)
    if not players:
        return {"error": "\u9078\u624b\u30c7\u30fc\u30bf\u306a\u3057", "url": race_url}
    line_input = [{"car_no": p["car_no"], "name": p["name"], "comment": p["comment"], "leg_type": p["leg_type"]} for p in players]
    line_info  = parse_line_groups(line_input)
    url_match    = re.search(r"/(\w+)/racedetail/(\d+)/", race_url)
    stadium_name = url_match.group(1) if url_match else ""
    race_id      = url_match.group(2) if url_match else ""
    honmei       = next((p for p in players if p["yoso_mark"] == "\u25ce"), None)
    first_place  = next((r for r in results if r["rank"] == 1), None)
    is_hit       = (first_place["car_no"] == honmei["car_no"]) if (first_place and honmei) else None
    time.sleep(1)
    return {
        "race": {"race_id": race_id, "stadium_name": stadium_name, "scraped_at": datetime.now().isoformat(), "player_count": len(players)},
        "entries":    players,
        "results":    results,
        "lines":      line_info,
        "race_order": race_order,
        "prediction_meta": {"honmei_car": honmei["car_no"] if honmei else None, "honmei_name": honmei["name"] if honmei else None, "is_honmei_hit": is_hit},
    }

if __name__ == "__main__":
    print("=== 動作確認 ===")
    r = scrape_and_format("https://keirin.kdreams.jp/aomori/racedetail/1220260610030001/")
    print(f"\u9078\u624b\u6570: {r['race']['player_count']}")
    print(f"\u7d50\u679c\u6570: {len(r['results'])}")
    for res in r["results"]:
        print(f"  {res['rank']}\u7740: {res['car_no']}\u756a {res['player_name']} {res['kimete']}")
    print(f"\u7684\u4e2d: {r['prediction_meta']['is_honmei_hit']}")
