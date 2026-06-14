import requests
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pickle
from datetime import datetime

SUPABASE_URL = "https://bjxosmqlmssxvoddeyae.supabase.co"
SUPABASE_KEY = "sb_publishable_HUOYksS-WVa6aXuyZCsflg_ZkmThDcK"
HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

def fetch_all(table, select="*"):
    all_data = []
    offset = 0
    while True:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/{table}?select={select}&limit=1000&offset={offset}", headers=HEADERS)
        data = res.json()
        if not data: break
        all_data.extend(data)
        offset += 1000
        if len(data) < 1000: break
    return all_data

def build_features(entries, results, lines, races, bank_stats):
    df_e    = pd.DataFrame(entries)
    df_r    = pd.DataFrame(results)
    df_l    = pd.DataFrame(lines)
    df_race = pd.DataFrame(races)
    df_bank = pd.DataFrame(bank_stats)

    # レース情報を結合
    df_e = df_e.merge(df_race[["race_id","grade","race_type","player_count","stadium_code"]], on="race_id", how="left", suffixes=("","_race"))

    # バンク特性を結合
    if not df_bank.empty:
        df_e = df_e.merge(df_bank[["stadium_code","nige_rate","makuri_rate","sashi_rate"]], on="stadium_code", how="left")
    else:
        df_e["nige_rate"]   = 0.25
        df_e["makuri_rate"] = 0.30
        df_e["sashi_rate"]  = 0.45

    # ライン内順位
    line_map = {}
    for _, row in df_l.iterrows():
        cars = [int(c) for c in str(row["cars"]).split("-") if c.isdigit()]
        for pos, car_no in enumerate(cars, 1):
            line_map[(row["race_id"], car_no)] = {"position": pos, "line_size": len(cars), "is_leader": 1 if pos==1 else 0, "is_second": 1 if pos==2 else 0, "is_third": 1 if pos==3 else 0, "is_solo": 0}

    def get_line(row, key):
        return line_map.get((row["race_id"], row["car_no"]), {"position":0,"line_size":1,"is_leader":0,"is_second":0,"is_third":0,"is_solo":1}).get(key, 0)

    df_e["line_position"] = df_e.apply(lambda r: get_line(r, "position"), axis=1)
    df_e["line_size"]     = df_e.apply(lambda r: get_line(r, "line_size"), axis=1)
    df_e["is_leader"]     = df_e.apply(lambda r: get_line(r, "is_leader"), axis=1)
    df_e["is_second"]     = df_e.apply(lambda r: get_line(r, "is_second"), axis=1)
    df_e["is_third"]      = df_e.apply(lambda r: get_line(r, "is_third"), axis=1)
    df_e["is_solo"]       = df_e.apply(lambda r: get_line(r, "is_solo"), axis=1)

    # 数値変換
    leg_map        = {"逃":5,"捲":4,"両":3,"差":2,"追":1,"自":3}
    grade_map      = {"SS":7,"S1":6,"S2":5,"A1":4,"A2":3,"A3":2,"L1":4,"L2":3}
    race_grade_map = {"GP":7,"G1":6,"G2":5,"G3":4,"F1":3,"F2":2}
    race_type_map  = {"決勝":5,"準決勝":4,"選抜":3,"予選":2,"一般":1}
    grade_trust    = {"SS":0.436,"S1":0.396,"S2":0.366,"A1":0.433,"A2":0.495,"A3":0.558,"L1":0.705,"L2":0.5}

    df_e["leg_type_num"]   = df_e["leg_type"].map(leg_map).fillna(3)
    df_e["grade_num"]      = df_e["grade"].map(grade_map).fillna(3)
    df_e["race_grade_num"] = df_e["grade_race"].map(race_grade_map).fillna(2) if "grade_race" in df_e.columns else 2
    df_e["race_type_num"]  = df_e["race_type"].map(race_type_map).fillna(1)
    df_e["grade_trust"]    = df_e["grade"].map(grade_trust).fillna(0.4)
    df_e["period"]         = pd.to_numeric(df_e["period"], errors="coerce").fillna(80)
    df_e["generation"]     = df_e["period"].apply(lambda x: 1 if x>=110 else (2 if x>=90 else 3))

    # 脚質とバンク特性の相性スコア
    # 逃げ選手 × 逃げ有利バンク → 高スコア
    df_e["nige_rate"]   = pd.to_numeric(df_e["nige_rate"], errors="coerce").fillna(0.25)
    df_e["makuri_rate"] = pd.to_numeric(df_e["makuri_rate"], errors="coerce").fillna(0.30)
    df_e["sashi_rate"]  = pd.to_numeric(df_e["sashi_rate"], errors="coerce").fillna(0.45)

    df_e["bank_leg_match"] = df_e.apply(lambda r:
        r["nige_rate"]   if r["leg_type"] in ["逃"] else
        r["makuri_rate"] if r["leg_type"] in ["捲"] else
        r["sashi_rate"]  if r["leg_type"] in ["差","追"] else
        (r["nige_rate"] + r["sashi_rate"]) / 2,
        axis=1
    )

    # レース内統計
    race_stats = df_e.groupby("race_id").agg(
        score_mean=("current_score","mean"),
        score_std=("current_score","std"),
    ).reset_index()
    df_e = df_e.merge(race_stats, on="race_id", how="left")
    df_e["score_diff_from_mean"] = df_e["current_score"] - df_e["score_mean"]
    df_e["score_rank_in_race"]   = df_e.groupby("race_id")["current_score"].rank(ascending=False)

    # 直近4ヶ月統計
    df_e["total_races_4m"] = df_e["rank1_4m"].fillna(0)+df_e["rank2_4m"].fillna(0)+df_e["rank3_4m"].fillna(0)+df_e["rank_out_4m"].fillna(0)
    df_e["kimete_total"]   = df_e["kimete_nige"].fillna(0)+df_e["kimete_makuri"].fillna(0)+df_e["kimete_sashi"].fillna(0)+df_e["kimete_ma"].fillna(0)
    df_e["kimete_nige_rate"]   = df_e.apply(lambda r: r["kimete_nige"]/max(r["kimete_total"],1), axis=1)
    df_e["kimete_makuri_rate"] = df_e.apply(lambda r: r["kimete_makuri"]/max(r["kimete_total"],1), axis=1)
    df_e["kimete_sashi_rate"]  = df_e.apply(lambda r: r["kimete_sashi"]/max(r["kimete_total"],1), axis=1)

    # 着順フラグ
    df_r["is_top1"] = (df_r["rank"]==1).astype(int)
    df_r["is_top2"] = (df_r["rank"]<=2).astype(int)
    df_r["is_top3"] = (df_r["rank"]<=3).astype(int)

    df = df_e.merge(df_r[["race_id","car_no","rank","is_top1","is_top2","is_top3"]], on=["race_id","car_no"], how="left")
    df = df.dropna(subset=["rank"])
    print(f"学習データ: {len(df)}行")

    feature_cols = [
        "yoso_rank",
        "car_no","frame_no","current_score","gear_ratio",
        "leg_type_num","grade_num","period","generation","grade_trust",
        "win_rate_4m","top2_rate_4m","top3_rate_4m",
        "rank1_4m","rank2_4m","rank3_4m","rank_out_4m","total_races_4m",
        "kimete_nige","kimete_makuri","kimete_sashi","kimete_ma",
        "kimete_nige_rate","kimete_makuri_rate","kimete_sashi_rate",
        "wins_s","wins_b",
        "stadium_wins_year","last5years_at_stadium",
        "line_position","line_size","is_leader","is_second","is_third","is_solo",
        "race_grade_num","race_type_num","player_count",
        "score_std","score_diff_from_mean","score_rank_in_race",
        # バンク特性（新追加）
        "nige_rate","makuri_rate","sashi_rate","bank_leg_match",
    ]

    for col in feature_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else: df[col] = 0

    X = df[feature_cols].values
    print(f"特徴量: {len(feature_cols)}個")
    return X, df["is_top1"].values, df["is_top2"].values, df["is_top3"].values, feature_cols, df

def train_model(X, y, label, feature_cols):
    X_train,X_test,y_train,y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestClassifier(n_estimators=300, max_depth=12, min_samples_leaf=3, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    acc = accuracy_score(y_test, model.predict(X_test))
    print(f"  {label} 精度: {acc:.3f}")
    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1]
    print(f"  Top10:")
    for i in range(min(10, len(feature_cols))):
        print(f"    {i+1:2d}. {feature_cols[indices[i]]:35s}: {importances[indices[i]]:.4f}")
    return model

if __name__ == "__main__":
    print("="*60)
    print(f"競輪予想 バンク特性+2着率モデル {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    entries    = fetch_all("race_entries")
    results    = fetch_all("race_results", "race_id,car_no,rank")
    lines      = fetch_all("race_lines", "race_id,line_no,cars")
    races      = fetch_all("races", "race_id,grade,race_type,player_count,stadium_code")
    bank_stats = fetch_all("bank_stats")
    print(f"出走表:{len(entries)} 結果:{len(results)} ライン:{len(lines)} レース:{len(races)} バンク:{len(bank_stats)}")

    X, y_top1, y_top2, y_top3, feature_cols, df = build_features(entries, results, lines, races, bank_stats)

    print("\n【1着予測】")
    model_top1 = train_model(X, y_top1, "1着", feature_cols)
    print("\n【2着以内予測】")
    model_top2 = train_model(X, y_top2, "2着以内", feature_cols)
    print("\n【3着以内予測】")
    model_top3 = train_model(X, y_top3, "3着以内", feature_cols)

    with open("keirin_model.pkl", "wb") as f:
        pickle.dump({"model_top1": model_top1, "model_top2": model_top2, "model_top3": model_top3, "feature_cols": feature_cols}, f)
    print("\nkeirin_model.pkl 保存完了")