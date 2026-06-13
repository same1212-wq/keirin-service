"""
競輪予想 機械学習モデル（全特徴量版）
========================================
追加特徴量：
・記者予想ランク（yoso_rank）← 最重要
・SB得点（wins_s, wins_b）
・決まり手の種類別実績
・期別（ベテラン/新人）
・グレード別モデル
・ライン情報（先頭/番手/単騎）
・レースグレード
"""
import requests
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pickle
from datetime import datetime

SUPABASE_URL = "https://bjxosmqlmssxvoddeyae.supabase.co"
SUPABASE_KEY = "sb_publishable_HUOYksS-WVa6aXuyZCsflg_ZkmThDcK"
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

def fetch_all(table, select="*"):
    all_data = []
    offset = 0
    while True:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}?select={select}&limit=1000&offset={offset}",
            headers=HEADERS
        )
        data = res.json()
        if not data:
            break
        all_data.extend(data)
        offset += 1000
        if len(data) < 1000:
            break
    return all_data

def build_features(entries, results, lines, races):
    df_e = pd.DataFrame(entries)
    df_r = pd.DataFrame(results)
    df_l = pd.DataFrame(lines)
    df_race = pd.DataFrame(races)

    # レース情報を結合（grade・race_type）
    df_e = df_e.merge(
        df_race[["race_id","grade","race_type","player_count"]],
        on="race_id", how="left", suffixes=("","_race")
    )

    # ライン内順位を計算
    line_map = {}
    for _, row in df_l.iterrows():
        cars = [int(c) for c in str(row["cars"]).split("-") if c.isdigit()]
        for pos, car_no in enumerate(cars, 1):
            line_map[(row["race_id"], car_no)] = {
                "line_no":   row["line_no"],
                "position":  pos,
                "line_size": len(cars),
                "is_leader": 1 if pos == 1 else 0,
                "is_second": 1 if pos == 2 else 0,
                "is_third":  1 if pos == 3 else 0,
                "is_solo":   0,
            }

    def get_line_info(row, key):
        return line_map.get((row["race_id"], row["car_no"]), {
            "line_no": 0, "position": 0, "line_size": 1,
            "is_leader": 0, "is_second": 0, "is_third": 0, "is_solo": 1
        }).get(key, 0)

    df_e["line_position"] = df_e.apply(lambda r: get_line_info(r, "position"), axis=1)
    df_e["line_size"]     = df_e.apply(lambda r: get_line_info(r, "line_size"), axis=1)
    df_e["is_leader"]     = df_e.apply(lambda r: get_line_info(r, "is_leader"), axis=1)
    df_e["is_second"]     = df_e.apply(lambda r: get_line_info(r, "is_second"), axis=1)
    df_e["is_third"]      = df_e.apply(lambda r: get_line_info(r, "is_third"), axis=1)
    df_e["is_solo"]       = df_e.apply(lambda r: get_line_info(r, "is_solo"), axis=1)

    # 脚質・級班・グレードを数値化
    leg_map = {"逃": 5, "捲": 4, "両": 3, "差": 2, "追": 1, "自": 3}
    grade_map = {"SS": 7, "S1": 6, "S2": 5, "A1": 4, "A2": 3, "A3": 2, "L1": 4, "L2": 3}
    race_grade_map = {"GP": 7, "G1": 6, "G2": 5, "G3": 4, "F1": 3, "F2": 2}
    race_type_map = {"決勝": 5, "準決勝": 4, "選抜": 3, "予選": 2, "一般": 1}

    df_e["leg_type_num"]    = df_e["leg_type"].map(leg_map).fillna(3)
    df_e["grade_num"]       = df_e["grade"].map(grade_map).fillna(3)
    df_e["race_grade_num"]  = df_e["grade_race"].map(race_grade_map).fillna(2) if "grade_race" in df_e.columns else df_e.get("grade", "F2").map(race_grade_map).fillna(2)
    df_e["race_type_num"]   = df_e["race_type"].map(race_type_map).fillna(1)

    # 期別から世代を計算（期別が大きいほど新人）
    df_e["period"] = pd.to_numeric(df_e["period"], errors="coerce").fillna(80)
    df_e["generation"] = df_e["period"].apply(lambda x: 1 if x >= 110 else (2 if x >= 90 else 3))

    # 総レース数・完走率
    df_e["total_races_4m"] = (
        df_e["rank1_4m"].fillna(0) + df_e["rank2_4m"].fillna(0) +
        df_e["rank3_4m"].fillna(0) + df_e["rank_out_4m"].fillna(0)
    )
    df_e["completion_rate"] = df_e.apply(
        lambda r: r["total_races_4m"] / max(r["total_races_4m"], 1), axis=1
    )

    # 先行系決まり手の割合
    df_e["kimete_total"] = (
        df_e["kimete_nige"].fillna(0) + df_e["kimete_makuri"].fillna(0) +
        df_e["kimete_sashi"].fillna(0) + df_e["kimete_ma"].fillna(0)
    )
    df_e["nige_rate"] = df_e.apply(
        lambda r: r["kimete_nige"] / max(r["kimete_total"], 1), axis=1
    )
    df_e["makuri_rate"] = df_e.apply(
        lambda r: r["kimete_makuri"] / max(r["kimete_total"], 1), axis=1
    )

    # 3着以内・1着のフラグ
    df_r["is_top3"] = (df_r["rank"] <= 3).astype(int)
    df_r["is_top1"] = (df_r["rank"] == 1).astype(int)

    df = df_e.merge(
        df_r[["race_id","car_no","rank","is_top3","is_top1"]],
        on=["race_id","car_no"], how="left"
    )
    df = df.dropna(subset=["rank"])
    print(f"学習データ: {len(df)}行")

    feature_cols = [
        # 記者予想（最重要）
        "yoso_rank",
        # 基本情報
        "car_no", "frame_no", "current_score", "gear_ratio",
        "leg_type_num", "grade_num", "period", "generation",
        # 直近4ヶ月成績
        "win_rate_4m", "top2_rate_4m", "top3_rate_4m",
        "rank1_4m", "rank2_4m", "rank3_4m", "rank_out_4m",
        "total_races_4m",
        # 決まり手
        "kimete_nige", "kimete_makuri", "kimete_sashi", "kimete_ma",
        "nige_rate", "makuri_rate",
        # SB
        "wins_s", "wins_b",
        # 同走路・当所成績
        "stadium_wins_year", "last5years_at_stadium",
        # ライン情報
        "line_position", "line_size",
        "is_leader", "is_second", "is_third", "is_solo",
        # レース情報
        "race_grade_num", "race_type_num", "player_count",
    ]

    for col in feature_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0

    X = df[feature_cols].values
    y_top1 = df["is_top1"].values
    y_top3 = df["is_top3"].values

    print(f"特徴量: {len(feature_cols)}個")
    print(f"1着サンプル: {y_top1.sum()}件 / 3着以内: {y_top3.sum()}件")
    return X, y_top1, y_top3, feature_cols, df

def train_model(X, y, label=""):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    model = RandomForestClassifier(
        n_estimators=300, max_depth=12,
        min_samples_leaf=3, random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)
    acc = accuracy_score(y_test, model.predict(X_test))
    print(f"  {label} 精度: {acc:.3f}")
    return model, X_test, y_test

if __name__ == "__main__":
    print("="*60)
    print("競輪予想 全特徴量モデル再学習")
    print(f"実行: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    print("\nデータ取得中...")
    entries = fetch_all("race_entries")
    results = fetch_all("race_results", "race_id,car_no,rank")
    lines   = fetch_all("race_lines", "race_id,line_no,cars")
    races   = fetch_all("races", "race_id,grade,race_type,player_count")
    print(f"出走表:{len(entries)} 結果:{len(results)} ライン:{len(lines)} レース:{len(races)}")

    X, y_top1, y_top3, feature_cols, df = build_features(entries, results, lines, races)

    print("\nモデル学習中...")
    model_top1, _, _ = train_model(X, y_top1, "1着予測")
    model_top3, _, _ = train_model(X, y_top3, "3着以内予測")

    # 特徴量重要度
    importances = model_top1.feature_importances_
    indices = np.argsort(importances)[::-1]
    print(f"\n【特徴量重要度 Top15（1着モデル）】")
    for i in range(min(15, len(feature_cols))):
        print(f"  {i+1:2d}. {feature_cols[indices[i]]:25s}: {importances[indices[i]]:.4f}")

    # モデル保存
    with open("keirin_model.pkl", "wb") as f:
        pickle.dump({
            "model_top1": model_top1,
            "model_top3": model_top3,
            "feature_cols": feature_cols,
        }, f)
    print("\nモデルを keirin_model.pkl に保存しました")