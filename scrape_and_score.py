import os, sys, json, subprocess, re, pathlib
import pandas as pd
from datetime import datetime, timezone, timedelta
import yaml

# ---------- helpers ----------
JST = timezone(timedelta(hours=9))

def jst_now_iso():
    return datetime.now(JST).isoformat()

def calc_since_date(days_back: int) -> str:
    dt = datetime.now(JST) - timedelta(days=days_back)
    return dt.date().isoformat()

def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def regex_score(text: str, weights: dict) -> (int, dict):
    score = 0
    hits = {}
    for pattern, w in weights.items():
        if re.search(pattern, text):
            score += int(w)
            hits[pattern] = hits.get(pattern, 0) + 1
    return score, hits

def run_snscrape(query: str, since: str, until: str=None, max_count: int=300):
    """Call snscrape CLI and stream JSONL. Stop after max_count lines."""
    q = f'{query} since:{since}'
    if until:
        q += f' until:{until}'
    cmd = ["snscrape", "--jsonl", "twitter-search", q]
    results = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") as proc:
        for i, line in enumerate(proc.stdout):
            if i >= max_count:
                try:
                    proc.kill()
                except Exception:
                    pass
                break
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results

def normalize_row(obj):
    user = obj.get("user") or {}
    return {
        "timestamp": jst_now_iso(),
        "tweet_id": obj.get("id"),
        "tweet_date": obj.get("date"),
        "user_id": user.get("id"),
        "handle": user.get("username"),
        "name": user.get("displayname"),
        "followers": user.get("followersCount"),
        "location": user.get("location"),
        "tweet_text": obj.get("content"),
        "url": obj.get("url")
    }

# ---------- main ----------
def main():
    # 設定ファイル（なければ sample を使う）
    cfg_path = "config.yaml" if pathlib.Path("config.yaml").exists() else "config.sample.yaml"
    cfg = load_yaml(cfg_path)

    days_back       = cfg["scraper"]["days_back"]
    max_per_query   = cfg["scraper"]["max_per_query"]
    weights         = cfg["scoring"]["weights"]
    threshold       = cfg["scoring"]["threshold"]
    min_len         = cfg["filters"]["min_len"]
    exclude_re      = re.compile(cfg["filters"]["exclude_company_patterns"])

    since = calc_since_date(days_back)

    # クエリ読み込み
    if not pathlib.Path("queries.json").exists():
        print("queries.json not found. Exiting.")
        sys.exit(0)
    with open("queries.json", "r", encoding="utf-8") as f:
        queries = json.load(f)

    # 収集
    rows = []
    for q in queries:
        res = run_snscrape(q["query"], since=since, max_count=max_per_query)
        for r in res:
            row = normalize_row(r)
            row["query_name"] = q["name"]
            if not row["tweet_text"] or len(row["tweet_text"]) < min_len:
                continue
            hay = " ".join(filter(None, [row.get("tweet_text"), row.get("name"), row.get("location")]))
            score, hits = regex_score(hay, weights)
            row["score_total"]  = score
            row["score_detail"] = json.dumps(hits, ensure_ascii=False)
            bio = row.get("name") or ""
            if exclude_re.search(bio):
                continue
            rows.append(row)

    # DataFrame 構築（0件でも落ちないように）
    expected_cols = [
        "timestamp","tweet_id","tweet_date","user_id","handle","name",
        "followers","location","tweet_text","url","query_name",
        "score_total","score_detail"
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        print("Scraped 0 tweets. Writing empty outputs and continuing.")
        df = pd.DataFrame(columns=expected_cols)
        dff = df.copy()
    else:
        for c in expected_cols:
            if c not in df.columns:
                df[c] = None
        df  = df.drop_duplicates(subset=["tweet_id"]).sort_values("score_total", ascending=False)
        dff = df[df["score_total"] >= threshold].copy()

    # CSV 出力
    out_dir = pathlib.Path("out"); out_dir.mkdir(exist_ok=True)
    df.to_csv(out_dir / "raw_candidates.csv", index=False, encoding="utf-8")
    dff.to_csv(out_dir / "filtered_candidates.csv", index=False, encoding="utf-8")

    # Google Sheets へ反映
    try:
        from google.oauth2.service_account import Credentials
        import gspread

        sheets_cfg     = cfg["google_sheets"]
        spreadsheet_id = sheets_cfg["spreadsheet_id"]
        ws_raw         = sheets_cfg["worksheet_raw"]
        ws_filt        = sheets_cfg["worksheet_filtered"]
        sa_env         = sheets_cfg["service_account_json_env"]
        sa_json        = os.environ.get(sa_env)

        if spreadsheet_id and sa_json:
            creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ])
            gc = gspread.authorize(creds)
            sh = gc.open_by_key(spreadsheet_id)

            def upsert_ws(title, dataframe: pd.DataFrame):
                try:
                    ws = sh.worksheet(title)
                except Exception:
                    ws = sh.add_worksheet(title=title, rows="100", cols="20")
                ws.clear()
                if dataframe.empty:
                    ws.update("A1", [expected_cols])
                    return
                headers = list(dataframe.columns)
                ws.update("A1", [headers])
                values = dataframe.astype(str).values.tolist()
                chunk = 500
                for i in range(0, len(values), chunk):
                    ws.update(f"A{2+i}", values[i:i+chunk])

            upsert_ws(ws_raw, df)
            upsert_ws(ws_filt, dff)
            print("Google Sheets updated.")
        else:
            print("Google Sheets not configured; skipped upload.")
    except Exception as e:
        print("Sheets upload skipped or failed:", e)

if __name__ == "__main__":
    main()
