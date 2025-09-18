# Porty X Candidates AutoList (Cost-0 Edition)

**目的**: X（Twitter）の公開検索結果を無料で収集し、不動産仕入/買取の経験者・転職意向者をスコアリングして**Googleスプレッドシートに自動蓄積**します。  
DM送付は別担当が実施する前提です。

> ⚠️ 免責: 本リポジトリは学習/内製用途のサンプルです。X の利用規約や各種法令・プライバシーポリシーを遵守のうえ、ご利用ください。

---

## 構成

- `snscrape` で検索 → JSON 取得（無料）
- Python で正規表現スコアリング
- `gspread` + サービスアカウント で Google Sheets に保存（無料）
- GitHub Actions で **毎日自動実行**

```
.
├─ queries.json               # 検索クエリ一覧（編集OK）
├─ config.sample.yaml         # 設定（config.yaml にコピーして編集）
├─ src/
│  ├─ utils.py
│  └─ scrape_and_score.py     # メインスクリプト
├─ requirements.txt
├─ .github/workflows/scrape.yml
└─ README.md
```

---

## セットアップ

### 1) Google Sheets の準備
1. 新規スプレッドシートを作成し、URL の `/d/` と `/edit` の間の ID を控える（例: `1AbCd...`）。
2. GCP で**サービスアカウント**を作成し、キーを JSON で作成。
3. そのサービスアカウントのメール（`xxx@xxx.iam.gserviceaccount.com`）に**スプレッドシートの編集権限**を付与（共有）。

### 2) GitHub リポジトリを作成
1. 本プロジェクトを GitHub に push。
2. GitHub のリポジトリ `Settings > Secrets and variables > Actions` で以下を登録：
   - `GOOGLE_CREDENTIALS_JSON`：サービスアカウント JSON の**中身**をそのまま貼り付け
   - `SHEET_ID`：スプレッドシートの ID

### 3) 設定ファイル
`config.sample.yaml` を `config.yaml` にコピーし、以下を編集：

```yaml
google_sheets:
  spreadsheet_id: "<SHEET_ID>"
  worksheet_raw: "raw_candidates"
  worksheet_filtered: "filtered_candidates"
  service_account_json_env: "GOOGLE_CREDENTIALS_JSON"

scraper:
  days_back: 7
  max_per_query: 300

scoring:
  threshold: 70
  weights:
    "(用地\s*仕入|仕入\s*営業|買取\s*再販|任意売却\s*営業|売買\s*仲介)": 40
    "(辞めたい|有給\s*消化|退職(代行)?|求職中|転職\s*活動中|次の仕事)": 25
    "(宅建|宅地建物取引士|査定|査定書|レインズ)": 20
    "(東京|神奈川|千葉|埼玉)": 10
    "(いいね|RT|リツイート)": 5

filters:
  min_len: 10
  exclude_company_patterns: "(採用|求人|株式会社|Inc\.|会社|代理店|募集)"
```

### 4) ローカル実行（初回テスト）
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# snscrape は pip ではなく OS パッケージ or pipx 推奨。macOS は brew で: brew install snscrape
# Windows は pipx 経由などで導入可
export GOOGLE_CREDENTIALS_JSON='{"type":"service_account", ...}'  # JSON 文字列
export SHEET_ID='<your_spreadsheet_id>'
cp config.sample.yaml config.yaml && sed -i '' "s/YOUR_SHEET_ID/$SHEET_ID/" config.yaml

python src/scrape_and_score.py
```

---

## GitHub Actions（自動実行）

- `.github/workflows/scrape.yml` が毎日 02:30 UTC（**JST 11:30**）に実行します。  
- 成果は `raw_candidates` と `filtered_candidates` シートに反映。

手動実行: GitHub の Actions タブで `Run workflow`。

---

## クエリ編集のコツ

- `queries.json` に追記するだけでOK
- 除外語を増やす：`-求人 -採用 -募集 -派遣 -アルバイト ...`
- 活性アカウント優先：`min_faves:3` は snscrape のネイティブ検索構文に準拠しないため、
  一旦取得してから **followers や tweet 文字数**で足切りするのが堅実。

---

## よくある質問

**Q. DM も自動で？**  
A. 本リポジトリは**リスト作成まで**。DM は他担当が運用してください。Selenium 等での自動化は凍結リスクが上がります。

**Q. 収集範囲は？**  
A. `config.yaml` の `days_back` を調整。日次で回せば取りこぼしは少なめ。

**Q. 重複は？**  
A. `tweet_id` で重複排除しています。

**Q. 地域/スコアのロジックは？**  
A. `scoring.weights` を編集。例：中部/関西を加点するなど。

---

## ライセンス
MIT（自己責任でどうぞ）
