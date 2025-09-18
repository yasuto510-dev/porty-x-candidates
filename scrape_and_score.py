import os, sys, json, subprocess, tempfile, re
import pandas as pd
from datetime import datetime, timezone, timedelta
import yaml

from utils import calc_since_date, jst_now_iso, regex_score

def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def run_snscrape(query: str, since: str, until: str=None, max_count: int=300):
    q = f'{query} since:{since}'
    if until:
        q += f' until:{until}'
    cmd = ["snscrape", "--jsonl", "twitter-search", q]
    # Stream and stop after max_count lines
    results = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") as proc:
        for i, line in enumerate(proc.stdout):
            if i >= max_count:
                proc.kill()
                break
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return results

def normalize_row(obj):
    # snscrape tweet schema fields
    return {
        "timestamp": jst_now_iso(),
        "tweet_id": obj.get("id"),
        "tweet_date": obj.get("date"),
        "user_id": obj.get("user", {}).get("id") if obj.get("user") else None,
        "handle": obj.get("user", {}).get("username") if obj.get("user") else None,
        "name": obj.get("user", {}).get("displayname") if obj.get("user") else None,
        "followers": obj.get("user", {}).get("followersCount") if obj.get("user") else None,
        "location": obj.get("user", {}).get("location") if obj.get("user") else None,
        "tweet_text": obj.get("content"),
        "url": obj.get("url")
    }

def main():
    cfg_path = os.environ.get("CONFIG_PATH", "config.yaml")
    if not os.path.exists(cfg_path):
        cfg_path = "config.sample.yaml"
    cfg = load_yaml(cfg_path)

    days_back = cfg["scraper"]["days_back"]
    max_per_query = cfg["scraper"]["max_per_query"]
    weights = cfg["scoring"]["weights"]
    threshold = cfg["scoring"]["threshold"]
    min_len = cfg["filters"]["min_len"]
    exclude_company_pat = cfg["filters"]["exclude_company_patterns"]
    exclude_re = re.compile(exclude_company_pat)

    since = calc_since_date(days_back)

    # Load queries
    with open("queries.json", "r", encoding="utf-8") as f:
        queries = json.load(f)

    rows = []
    for q in queries:
        res = run_snscrape(q["query"], since=since, max_count=max_per_query)
        for r in res:
            row = normalize_row(r)
            row["query_name"] = q["name"]
            # basic filters
            if not row["tweet_text"] or len(row["tweet_text"]) < min_len:
                continue
            # score on tweet text + bio (name and location included)
            hay = " ".join([
                row.get("tweet_text") or "",
                row.get("name") or "",
                row.get("location") or ""
            ])
            score, hits = regex_score(hay, weights)
            row["score_total"] = score
            row["score_detail"] = json.dumps(hits, ensure_ascii=False)
            # exclude company-like accounts by name/bio heuristic
            bio = " ".join([row.get("name") or ""])
            if exclude_re.search(bio):
                continue
            rows.append(row)

    df = pd.DataFrame(rows).drop_duplicates(subset=["tweet_id"]).sort_values("score_total", ascending=False)
    print(f"Scraped {len(df)} unique tweets")

    # Save interim CSVs
    os.makedirs("out", exist_ok=True)
    raw_path = "out/raw_candidates.csv"
    filt_path = "out/filtered_candidates.csv"
    df.to_csv(raw_path, index=False, encoding="utf-8")

    dff = df[df["score_total"] >= threshold].copy()
    dff.to_csv(filt_path, index=False, encoding="utf-8")

    # Push to Google Sheets if configured
    try:
        from google.oauth2.service_account import Credentials
        import gspread

        sheets_cfg = cfg["google_sheets"]
        spreadsheet_id = sheets_cfg["spreadsheet_id"]
        ws_raw = sheets_cfg["worksheet_raw"]
        ws_filt = sheets_cfg["worksheet_filtered"]
        sa_env = sheets_cfg["service_account_json_env"]
        sa_json = os.environ.get(sa_env)

        if spreadsheet_id and sa_json:
            creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ])
            gc = gspread.authorize(creds)
            sh = gc.open_by_key(spreadsheet_id)

            # Helper to upsert worksheet
            def upsert_ws(name, dataframe):
                try:
                    ws = sh.worksheet(name)
                except:
                    ws = sh.add_worksheet(title=name, rows="100", cols="20")
                # Clear and set header + values
                ws.clear()
                if len(dataframe) == 0:
                    ws.update("A1", [["no_data"]])
                    return
                headers = list(dataframe.columns)
                ws.update("A1", [headers])
                values = dataframe.astype(str).values.tolist()
                # Batch update in chunks to avoid size limits
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
