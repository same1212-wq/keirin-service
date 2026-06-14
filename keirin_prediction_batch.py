"""
競輪予想 保存・照合スクリプト
================================
1. 当日レースを予想してai_predictionsに保存
2. レース結果と照合してis_honmei_hit・miss_reasonを更新
"""
import requests
import pandas as pd
import numpy as np
import pickle
import re
from datetime import datetime

SUPABASE_URL = "https://bjxosmqlmssxvoddeyae.supabase.co"
SUPABASE_KEY = "sb_publishable_HUOYksS-WVa6aXuyZCsflg_ZkmThDcK"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}
GET_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

# モデル読み込み
with open("keirin_model.pkl", "rb") as f:
    saved = pickle.load(f)
model_top1 = saved.get("model_top1") or saved.get("model")
model_top3 = saved.get("model_top3") or saved.get("model")
feature_cols = saved["feature_cols"]

# ============================================================
# 予想生成
# ============================================================
def predict_race(race_entries, race_lines):
    """1レース分の予想を生成して結果を返す"""
    if not race_entries:
        return None

    df = pd.DataFrame(race_entries)

    # ライン内順位
    line_position = {}
    for line in race_lines:
        cars = [int(c) for c in str(line["cars"]).split("-") if c.isdigit()]
        for pos, car_no in enumerate(cars, 1):
            line_position[car_no] = (line["line_no"], pos, len(cars))

    df["line_position"] = df["car_no"].map(lambda x: line_position.get(x, (0,0,1))[1])
    df["line_size"]     = df["car_no"].map(lambda x: line_position.get(x, (0,0,1))[2])
    df["is_leader"]     = (df["line_position"] == 1).astype(int)
    df["is_second"]     = (df["line_position"] == 2).astype(int)
    df["is_solo"]       = (df["line_position"] == 0).astype(int)

    leg_map   = {"逃": 5, "捲": 4, "両": 3, "差": 2, "追": 1, "自": 3}
    grade_map = {"SS": 7, "S1": 6, "S2": 5, "A1": 4, "A2": 3, "A3": 2, "L1": 4, "L2": 3}
    df["leg_type_num"] = df["leg_type"].map(leg_map).fillna(3)
    df["grade_num"]    = df["grade"].map(grade_map).fillna(3)

    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    X = df[feature_cols].values

    if hasattr(model_top1, "predict_proba"):
        df["prob_top1"] = model_top1.predict_proba(X)[:, 1]
    else:
        df["prob_top1"] = 0.1

    if model_top3 and hasattr(model_top3, "predict_proba"):
        df["prob_top3"] = model_top3.predict_proba(X)[:, 1]
    else:
        df["prob_top3"] = df["prob_top1"]

    df["combined"] = df["prob_top1"] * 0.6 + df["prob_top3"] * 0.4
    df_sorted = df.sort_values("combined", ascending=False).reset_index(drop=True)

    # 上位3頭
    top = df_sorted.head(3)
    cars = [int(r["car_no"]) for _, r in top.iterrows()]
    names = [str(r.get("name", r.get("player_name", "不明"))) for _, r in top.iterrows()]

    # 買い目生成
    nisha_tan   = f"{cars[0]}→{cars[1]}"
    nisha_fuku  = f"{cars[0]}={cars[1]}"
    sanren_tan  = f"{cars[0]}→{cars[1]}→{cars[2]}" if len(cars) >= 3 else ""
    sanren_fuku = "-".join(map(str, sorted(cars[:3]))) if len(cars) >= 3 else ""
    wide_bets   = []
    if len(cars) >= 2:
        wide_bets.append(f"{cars[0]}={cars[1]}")
    if len(cars) >= 3:
        wide_bets.append(f"{cars[0]}={cars[2]}")
        wide_bets.append(f"{cars[1]}={cars[2]}")
    wide = " / ".join(wide_bets)

    # ライン情報テキスト
    line_texts = []
    for line in race_lines:
        line_texts.append(f"L{line['line_no']}:{line['cars']}({line['names']})")
    line_info = " | ".join(line_texts)

    return {
        "honmei_car":   cars[0] if len(cars) > 0 else None,
        "honmei_name":  names[0] if len(names) > 0 else None,
        "taikou_car":   cars[1] if len(cars) > 1 else None,
        "taikou_name":  names[1] if len(names) > 1 else None,
        "ana_car":      cars[2] if len(cars) > 2 else None,
        "ana_name":     names[2] if len(names) > 2 else None,
        "top3_cars":    "-".join(map(str, cars[:3])),
        "nisha_tan":    nisha_tan,
        "nisha_fuku":   nisha_fuku,
        "sanren_tan":   sanren_tan,
        "sanren_fuku":  sanren_fuku,
        "wide":         wide,
        "confidence":   float(df_sorted.iloc[0]["prob_top1"]),
        "model_version": "rf_v2_top3",
        "line_info":    line_info,
        "df_sorted":    df_sorted,
    }

# ============================================================
# 予想をai_predictionsに保存
# ============================================================
def save_prediction(race_id, pred, race_grade="", race_type=""):
    if not pred:
        return False
    record = {
        "race_id":      race_id,
        "honmei_car":   pred["honmei_car"],
        "honmei_name":  pred["honmei_name"],
        "taikou_car":   pred["taikou_car"],
        "taikou_name":  pred["taikou_name"],
        "ana_car":      pred["ana_car"],
        "ana_name":     pred["ana_name"],
        "top3_cars":    pred["top3_cars"],
        "nisha_tan":    pred["nisha_tan"],
        "nisha_fuku":   pred["nisha_fuku"],
        "sanren_tan":   pred["sanren_tan"],
        "sanren_fuku":  pred["sanren_fuku"],
        "wide":         pred["wide"],
        "confidence":   pred["confidence"],
        "model_version": pred["model_version"],
        "line_info":    pred["line_info"],
        "race_grade":   race_grade,
        "race_type":    race_type,
        "is_honmei_hit": None,
        "miss_reason":  None,
        "created_at":   datetime.now().isoformat(),
    }
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/ai_predictions?on_conflict=race_id",
        headers=HEADERS,
        json=[record],
        timeout=15
    )
    return res.status_code in [200, 201, 204]

# ============================================================
# 結果照合・miss_reason更新
# ============================================================
def analyze_miss_reason(pred, results_df):
    """外れた理由を分析"""
    if pred["honmei_car"] is None:
        return "データなし"

    top3_actual = results_df[results_df["rank"] <= 3]["car_no"].tolist()
    honmei_rank = results_df[results_df["car_no"] == pred["honmei_car"]]["rank"].values
    honmei_rank = int(honmei_rank[0]) if len(honmei_rank) > 0 else 99

    if honmei_rank == 1:
        return None  # 的中

    # 外れ理由を分類
    if honmei_rank >= 6:
        return "本命大敗（展開・落車・失格の可能性）"
    elif honmei_rank in [4, 5]:
        return "本命4〜5着（惜しい・ライン崩壊の可能性）"
    elif honmei_rank in [2, 3]:
        return "本命2〜3着（番手選手が台頭）"

    # 1着が穴選手かどうか
    winner_car = results_df[results_df["rank"] == 1]["car_no"].values
    if len(winner_car) > 0:
        winner_prob = pred["df_sorted"][pred["df_sorted"]["car_no"] == winner_car[0]]["prob_top1"].values
        if len(winner_prob) > 0 and winner_prob[0] < 0.05:
            return "大穴決着（予測困難なレース）"

    return "予想外の展開"

def update_results(race_id, pred):
    """レース結果と照合してDB更新"""
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/race_results?race_id=eq.{race_id}&order=rank",
        headers=GET_HEADERS
    )
    results = res.json()
    if not results:
        return False

    results_df = pd.DataFrame(results)
    top3_actual = results_df[results_df["rank"] <= 3]["car_no"].tolist()
    honmei_hit = pred["honmei_car"] in top3_actual if pred["honmei_car"] else False
    is_honmei_1st = results_df[results_df["rank"] == 1]["car_no"].values
    is_1st_hit = len(is_honmei_1st) > 0 and is_honmei_1st[0] == pred["honmei_car"]

    miss_reason = analyze_miss_reason(pred, results_df) if not is_1st_hit else None

    # sanren_fuku的中チェック
    top3_sorted = sorted(top3_actual[:3])
    pred_top3_sorted = sorted([int(c) for c in pred["top3_cars"].split("-") if c.isdigit()])
    sanren_fuku_hit = top3_sorted == pred_top3_sorted

    update_data = {
        "is_honmei_hit":    bool(is_1st_hit),
        "miss_reason":      miss_reason,
        "rinrin_comment":   f"本命{pred['honmei_car']}番{'的中！' if is_1st_hit else '外れ'}　3連複{'的中！' if sanren_fuku_hit else '外れ'}",
    }
    res2 = requests.patch(
        f"{SUPABASE_URL}/rest/v1/ai_predictions?race_id=eq.{race_id}",
        headers=GET_HEADERS | {"Content-Type": "application/json", "Prefer": "return=minimal"},
        json=update_data,
        timeout=15
    )
    return res2.status_code == 204

# ============================================================
# メイン：当日の全レースを予想・保存
# ============================================================
def run_prediction_batch(date_str=None, mode="predict"):
    """
    mode="predict" : 予想を生成してai_predictionsに保存
    mode="update"  : レース結果と照合してis_honmei_hitを更新
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"{'='*60}")
    print(f"りんりん予想バッチ [{mode}] {date_str}")
    print(f"{'='*60}")

    # 当日レースを取得
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/races?race_date=eq.{date_str}&order=race_id",
        headers=GET_HEADERS
    )
    races = res.json()
    print(f"対象レース数: {len(races)}")

    success = 0
    for i, race in enumerate(races, 1):
        race_id = race["race_id"]
        stadium = race["stadium_code"]
        grade   = race.get("grade", "")
        rtype   = race.get("race_type", "")

        print(f"[{i:3d}/{len(races)}] {stadium} {race_id[-4:]}", end=" ")

        if mode == "predict":
            # 出走表・ライン取得
            res_e = requests.get(
                f"{SUPABASE_URL}/rest/v1/race_entries?race_id=eq.{race_id}&order=car_no",
                headers=GET_HEADERS
            )
            res_l = requests.get(
                f"{SUPABASE_URL}/rest/v1/race_lines?race_id=eq.{race_id}&order=line_no",
                headers=GET_HEADERS
            )
            entries = res_e.json()
            lines   = res_l.json()

            pred = predict_race(entries, lines)
            if pred and save_prediction(race_id, pred, grade, rtype):
                print(f"-> ◎{pred['honmei_car']}番 {pred['honmei_name']} "
                      f"確率:{pred['confidence']:.1%} "
                      f"3連単:{pred['sanren_tan']} "
                      f"3連複:{pred['sanren_fuku']}")
                success += 1
            else:
                print("-> エラー")

        elif mode == "update":
            # ai_predictionsから予想を取得
            res_p = requests.get(
                f"{SUPABASE_URL}/rest/v1/ai_predictions?race_id=eq.{race_id}",
                headers=GET_HEADERS
            )
            preds = res_p.json()
            if not preds:
                print("-> 予想なし")
                continue

            pred_record = preds[0]
            # レース結果取得
            res_r = requests.get(
                f"{SUPABASE_URL}/rest/v1/race_results?race_id=eq.{race_id}&order=rank&limit=1",
                headers=GET_HEADERS
            )
            results = res_r.json()
            if not results:
                print("-> 結果未確定")
                continue

            # 全着順を取得
            res_r_all = requests.get(
                f"{SUPABASE_URL}/rest/v1/race_results?race_id=eq.{race_id}&order=rank",
                headers=GET_HEADERS
            )
            all_results = res_r_all.json()
            if not all_results:
                print("-> 結果未確定")
                continue

            # 実際の着順を取得
            rank_to_car = {r["rank"]: r["car_no"] for r in all_results}
            car_to_rank = {r["car_no"]: r["rank"] for r in all_results}
            actual_1st = rank_to_car.get(1)
            actual_2nd = rank_to_car.get(2)
            actual_3rd = rank_to_car.get(3)
            actual_top2 = set([actual_1st, actual_2nd])
            actual_top3 = set([actual_1st, actual_2nd, actual_3rd])

            # 予想データ取得
            honmei_car = pred_record["honmei_car"]
            taikou_car = pred_record["taikou_car"]
            ana_car    = pred_record["ana_car"]
            nisha_tan  = pred_record.get("nisha_tan", "")
            sanren_tan = pred_record.get("sanren_tan", "")
            sanren_fuku= pred_record.get("sanren_fuku", "")
            wide       = pred_record.get("wide", "")

            # 1着的中
            is_honmei_1st = (honmei_car == actual_1st)

            # 2車単的中（本命→対抗）
            hit_nisha_tan = (honmei_car == actual_1st and taikou_car == actual_2nd)

            # 2車複的中（本命・対抗が1〜2着）
            hit_nisha_fuku = ({honmei_car, taikou_car} == actual_top2)

            # 3連単的中
            if sanren_tan and "→" in sanren_tan:
                st_cars = [int(c) for c in sanren_tan.split("→") if c.isdigit()]
                hit_sanren_tan = (
                    len(st_cars) >= 3 and
                    st_cars[0] == actual_1st and
                    st_cars[1] == actual_2nd and
                    st_cars[2] == actual_3rd
                )
            else:
                hit_sanren_tan = False

            # 3連複的中（予想上位3頭が実際の1〜3着と一致）
            if sanren_fuku and "-" in sanren_fuku:
                sf_cars = set([int(c) for c in sanren_fuku.split("-") if c.isdigit()])
                hit_sanren_fuku = (sf_cars == actual_top3)
            else:
                pred_top3 = set(filter(None, [honmei_car, taikou_car, ana_car]))
                hit_sanren_fuku = (pred_top3 == actual_top3)

            # ワイド的中（3通り）
            wide_pairs = []
            if honmei_car and taikou_car:
                wide_pairs.append({honmei_car, taikou_car})
            if honmei_car and ana_car:
                wide_pairs.append({honmei_car, ana_car})
            if taikou_car and ana_car:
                wide_pairs.append({taikou_car, ana_car})

            hit_wide1 = len(wide_pairs) > 0 and wide_pairs[0].issubset(actual_top3)
            hit_wide2 = len(wide_pairs) > 1 and wide_pairs[1].issubset(actual_top3)
            hit_wide3 = len(wide_pairs) > 2 and wide_pairs[2].issubset(actual_top3)

            # miss_reason判定
            if is_honmei_1st:
                miss_reason = None
            else:
                honmei_rank = car_to_rank.get(honmei_car, 99)
                if honmei_rank >= 6:
                    miss_reason = "本命大敗（展開・落車・失格の可能性）"
                elif honmei_rank in [4, 5]:
                    miss_reason = "本命4〜5着（惜しい）"
                elif honmei_rank in [2, 3]:
                    miss_reason = "本命2〜3着（番手選手が台頭）"
                else:
                    miss_reason = "予想外の展開"

            # 配当金をSupabaseから取得（payoutsテーブルがあれば）
            # 予想買い目の配当金を特定
            nisha_tan_key  = f"{honmei_car}-{taikou_car}" if honmei_car and taikou_car else ""
            nisha_fuku_key = "=".join(map(str, sorted([honmei_car, taikou_car]))) if honmei_car and taikou_car else ""
            top3_list = [int(c) for c in (pred_record.get("top3_cars") or "").split("-") if c.isdigit()]
            sanren_tan_key  = "-".join(map(str, top3_list)) if len(top3_list) >= 3 else ""
            sanren_fuku_key = "=".join(map(str, sorted(top3_list[:3]))) if len(top3_list) >= 3 else ""

            # 払戻テーブルから配当金を取得
            from keirin_data_formatter import extract_payouts
            from bs4 import BeautifulSoup
            payouts = {}
            try:
                res_page = requests.get(
                    f"https://keirin.kdreams.jp/{race[chr(115)+chr(116)+chr(97)+chr(100)+chr(105)+chr(117)+chr(109)+chr(95)+chr(99)+chr(111)+chr(100)+chr(101)]}/racedetail/{race_id}/",
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                    timeout=20
                )
                if res_page.status_code == 200:
                    psoup = BeautifulSoup(res_page.content, "html.parser")
                    payouts = extract_payouts(psoup)
            except Exception as e:
                print(f"(配当取得失敗:{e})", end=" ")
                payouts = {}

            # 各賭け式の配当金
            p_nisha_tan   = payouts.get(nisha_tan_key)
            p_nisha_fuku  = payouts.get(nisha_fuku_key)
            p_sanren_tan  = payouts.get(sanren_tan_key)
            p_sanren_fuku = payouts.get(sanren_fuku_key)

            # ワイド配当（3通り）
            wide_pairs_keys = []
            if honmei_car and taikou_car:
                wide_pairs_keys.append("=".join(map(str, sorted([honmei_car, taikou_car]))))
            if honmei_car and ana_car:
                wide_pairs_keys.append("=".join(map(str, sorted([honmei_car, ana_car]))))
            if taikou_car and ana_car:
                wide_pairs_keys.append("=".join(map(str, sorted([taikou_car, ana_car]))))
            p_wide1 = payouts.get(wide_pairs_keys[0]) if len(wide_pairs_keys) > 0 else None
            p_wide2 = payouts.get(wide_pairs_keys[1]) if len(wide_pairs_keys) > 1 else None
            p_wide3 = payouts.get(wide_pairs_keys[2]) if len(wide_pairs_keys) > 2 else None

            # 回収率計算（100円投資として）
            roi_nisha_tan   = p_nisha_tan / 100   if hit_nisha_tan  and p_nisha_tan   else (0 if hit_nisha_tan  else None)
            roi_nisha_fuku  = p_nisha_fuku / 100  if hit_nisha_fuku and p_nisha_fuku  else (0 if hit_nisha_fuku else None)
            roi_sanren_tan  = p_sanren_tan / 100  if hit_sanren_tan and p_sanren_tan  else (0 if hit_sanren_tan else None)
            roi_sanren_fuku = p_sanren_fuku / 100 if hit_sanren_fuku and p_sanren_fuku else (0 if hit_sanren_fuku else None)
            wide_hit_payouts = [p for p, h in [(p_wide1, hit_wide1),(p_wide2, hit_wide2),(p_wide3, hit_wide3)] if h and p]
            roi_wide = sum(wide_hit_payouts) / (len(wide_pairs_keys) * 100) if wide_hit_payouts else None

            # DB更新
            update_data = {
                "is_honmei_hit":    bool(is_honmei_1st),
                "hit_nisha_tan":    bool(hit_nisha_tan),
                "hit_nisha_fuku":   bool(hit_nisha_fuku),
                "hit_sanren_tan":   bool(hit_sanren_tan),
                "hit_sanren_fuku":  bool(hit_sanren_fuku),
                "hit_wide1":        bool(hit_wide1),
                "hit_wide2":        bool(hit_wide2),
                "hit_wide3":        bool(hit_wide3),
                "miss_reason":      miss_reason,
                "payout_nisha_tan":  p_nisha_tan,
                "payout_nisha_fuku": p_nisha_fuku,
                "payout_sanren_tan": p_sanren_tan,
                "payout_sanren_fuku":p_sanren_fuku,
                "payout_wide1":      p_wide1,
                "payout_wide2":      p_wide2,
                "payout_wide3":      p_wide3,
                "roi_nisha_tan":     roi_nisha_tan,
                "roi_nisha_fuku":    roi_nisha_fuku,
                "roi_sanren_tan":    roi_sanren_tan,
                "roi_sanren_fuku":   roi_sanren_fuku,
                "roi_wide":          roi_wide,
            }
            res_u = requests.patch(
                f"{SUPABASE_URL}/rest/v1/ai_predictions?race_id=eq.{race_id}",
                headers={**GET_HEADERS, "Content-Type": "application/json", "Prefer": "return=minimal"},
                json=update_data,
                timeout=15
            )
            if res_u.status_code == 204:
                hits = []
                if is_honmei_1st: hits.append("1着◎")
                if hit_nisha_tan:  hits.append("2車単◎")
                if hit_nisha_fuku: hits.append("2車複◎")
                if hit_sanren_tan: hits.append("3連単◎")
                if hit_sanren_fuku:hits.append("3連複◎")
                if hit_wide1 or hit_wide2 or hit_wide3: hits.append("ワイド◎")
                status = " ".join(hits) if hits else f"全外れ({miss_reason})"
                print(f"-> {status}")
                success += 1
            else:
                print(f"-> 更新エラー {res_u.status_code}")

    print(f"\n完了: {success}/{len(races)}")

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "predict"
    date = sys.argv[2] if len(sys.argv) > 2 else None
    run_prediction_batch(date, mode)