import re
import json
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

def jst_now_iso():
    return datetime.now(JST).isoformat()

def calc_since_date(days_back: int) -> str:
    dt = datetime.now(JST) - timedelta(days=days_back)
    return dt.date().isoformat()

def to_bool(v):
    if isinstance(v, bool): return v
    if isinstance(v, str): return v.lower() in ["1","true","yes","y"]
    return False

def regex_score(text: str, weights: dict) -> (int, dict):
    score = 0
    hits = {}
    for pattern, w in weights.items():
        if re.search(pattern, text):
            score += int(w)
            hits[pattern] = hits.get(pattern, 0) + 1
    return score, hits
