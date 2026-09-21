# BEACH NOTE

ビーチバレーの選手から、公式に発表された出場大会を探す静的サイトです。

**ローカルで公式情報を確認・抽出 → JSON生成 → GitHubへpush → GitHub Pagesで公開。** サーバー、DB、APIキーは不要です。スクレイピングは閲覧時にもGitHub Actions上でも実行しません。

## 今回収録した情報

2026年9月22日（日本時間）を基準に、開催前・開催中の25大会（中止告知1大会を含む）、171選手を収録しています。相馬・高萩の男女名簿から119ペアを抽出し、出場予定と補欠を分けています。JVAの大会別HTMLからアジア競技大会4ペア・アランヤ大会3ペアも追加しました。171人全員に予定があるわけではありません。予定がない公式紹介選手も検索できます。

- JBV: 当年ニュース、公認大会、年間予定、選手紹介、添付PDF
- JVA: 国内・国際大会一覧、川崎大会の概要・日程結果、アジア競技大会のメンバー、アランヤ・ドーハ大会の案内
- 横浜ビーチバレーボール連盟: PDFからリンクされたYBVF series 5の大会案内

参加者PDFは表のセル単位で解析。空白・髙/高・﨑/崎の差を吸収し、個別の表記差は `config/overrides.json` で対応しています。新しいシーディング表がある場合はそちらを優先します。相馬の9月17日のペア変更も新しい名簿に従って反映済みです。

JBV公式選手名鑑に写真が掲載されている選手は、公式画像へ直接リンクして一覧・選手ページに表示します。縦長画像はCSSで正方形にトリミングし、取得できない場合は選手名の頭文字へ戻します。

2026年BVT1の6大会について、167ペア分の公式最終順位を追加しました。全体では222選手・31大会を収録。選手ページの「過去の大会結果」から、順位・当時のペア・公式結果PDFを確認できます（立川立飛は女子のみ）。過去の全大会を網羅するものではありません。

**勝ち上がり予測、未発表の出場情報は収録しません。** 個々の試合の時刻・組み合わせは公式資料へのリンクで確認する構成です。

## まず画面を見る

Node.js 22以上を使用します。取得済みデータを含むため、Pythonのセットアップなしで起動できます。

```sh
npm ci
npm run dev
```

ブラウザで `http://127.0.0.1:4173` を開いてください。

```sh
npm run build      # dist/ に公開用ファイルだけを生成
npm run preview    # dist/ の公開時と同じ構成を確認
```

`dev` と `preview` は同じポートを使います。片方を終了してから起動するか `PORT=4174 npm run preview` を使用してください。HTMLファイルを直接開く `file://` ではJSONを取得できないため、上記のローカルサーバーを使います。

## 情報を更新する

このサイトの形式は一定ではないため、**コマンドだけを無人実行する前提にはしていません**。Codexなどで現状の掲載を見ながら更新してください。プロジェクト内の `AGENTS.md` に作業手順があります。

Codexの「BEACH NOTE 週次更新」を毎週月曜9:00（日本時間）に設定済みです。公式サイトの掲載形式と差分を確認し、テスト、コミット、push、Pagesの公開確認まで実行します。結果はこのタスクに報告されます。

初回だけ:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

更新と確認:

```sh
npm run update
.venv/bin/python -m scripts.audit_sources
```

1. `reports/update.json` の `issues`・`skipped` と、`reports/changes.json` を確認。
2. `reports/pdf-review.json` でPDF本文・PDF内リンクを確認。
3. `reports/external-candidates.json` で新しい主催者サイトへのリンクを確認。
4. 掲載形式が変わっていたらパーサーを修正。対応できない資料は目視確認し、出典付きで `config/overrides.json` に記録。
5. テスト・画面確認後、変更をコミットしてpush。

原本は `.cache/http/` に保存されます。本文ハッシュ、ETag、Last-Modified、取得日時も保存します。同じURLのPDF差し替えも検知できるよう毎回再確認します。1リクエストあたり最低1.2秒、1実行あたり記事160件・名簿PDF160件に制限しています。robots.txtの制限がある場合は尊重し、取得できなかった場合はレポートに記録します。初回確認ではJBVのrobots.txtはHTTP 500でした。再利用条件の確認状況は `docs/source-review-2026-09-22.md` を参照してください。

ネットワークを使わず、保存済み原本で解析をやり直すには:

```sh
.venv/bin/python -m scripts.update --offline
```

`--offline` は取得日時を更新しません。公開データには原本の最終確認日時と生成日時を別々に記録します。基準日は日本時間の今日です。特定日の再現には `--as-of 2026-09-22` を付けます。

ネットワークエラー・取得上限超過・未開催大会の予期しない消失・不正な名簿がある場合、従来の公開ファイルを保持します。未対応PDFは確認事項として記録し、該当大会に「確認中」と表示します。画像PDFをOCRした内容は未検証のまま自動公開しません。必要に応じてOCR・目視確認・手動補正する拡張点を用意しています。

### 別ドメインを確認する場合

`config/sources.json` の `allowedHosts` と `reviewPages` に、**公式資料から辿れた大会情報ページ**を追加します。確認先は最大10ドメインです。新しいドメインは自動で無制限に巡回しません。リンク元・確認結果は `docs/source-review-YYYY-MM-DD.md` に残します。

外部ページの取得結果は `reports/external-review.json` に保存します。異なるサイトの任意のHTMLを万能に自動解析する機能ではありません。掲載形式を確認したうえで、必要なパーサーを追加するか、出典付きの確認済み情報を補正ファイルに登録します。申込フォームへの送信やログインは行いません。

### 過去の結果を更新・追加する

`npm run update` は `config/sources.json` の `history.events` に登録した大会の結果ページも確認し、その時点でリンクされた結果PDFを再取得します。6大会の既存結果も毎回再解析されます。追加する大会は、まず公式の掲載形式と最終順位を確認して登録してください。

`scripts/history.py` は「試合結果順位」の明示された表だけを扱います。予選プール順位やトーナメントの勝ち上がりから順位を計算しません。表形式・年度・男女区分が想定と異なる場合は、公開JSONを変更せず停止します。大阪女子の結合セルはPDF画像で確認した補正を `history.events[].corrections` に記録しています。原本が変われば補正も再確認が必要です。

### 手動補正

`config/overrides.json`:

- `aliases`: 同一選手と確認できた氏名の表記差。氏名だけでは区別できない同姓同名は手動確認。
- `events`: 大会IDをキーに、日程・名称・`relatedSources` などを補正。
- `entries`: 大会IDをキーに、**大会全体の名簿**を置換。各行には `names`（2名）、`gender`、`status`、`sourceUrl` が必要。
- `ignoredPages`: 大会情報ではない記事などを明示的に除外。
- `removedEvents`: 未開催の大会を収録対象から外すときに、大会IDと確認理由を記録。

補正は根拠となる公式資料を確認してから行ってください。生の原本・連絡先・申込者情報は公開用JSONに入れません。

## GitHub Pages

リポジトリ: `misoclub-apps/mc-beach-volleyball`

リポジトリの **Settings → Pages → Source → GitHub Actions** を選択します。`main` へのpushで `.github/workflows/pages.yml` がビルド・公開します。ワークフローは、すでに取得済みのJSONを使うだけです。

公開先: `https://misoclub.pro/mc-beach-volleyball/`

組織に設定済みの独自ドメインを引き継いでいます。GitHub標準URLは `https://misoclub-apps.github.io/mc-beach-volleyball/` です。リポジトリはPublic、PagesのHTTPSを有効に設定済みです。

相対URLとハッシュルーティングを使うため、GitHub Pagesのリポジトリ配下でも動作します。選手・大会ページのURLもそのまま共有できます。

```sh
git add .
git commit -m "data: refresh upcoming beach volleyball events"
git push origin main
```

## 検証

```sh
npm test                  # 検索、日付、データ参照、補欠・中止の扱い
npm run test:python       # 日付・PDF名簿・表記ゆれのパーサー
npx playwright install chromium  # 初回のみ
npm run test:e2e          # ブラウザ操作、アクセシビリティ、レスポンシブ
npm run build
```

## ファイル構成

```text
index.html / app.js / model.js   画面・ルーティング・検索
styles.css / tokens.css         レスポンシブ表示・色・文字
public/data/beach.json          公開するデータ（Git管理）
scripts/update.py               取得・検証・JSON生成
scripts/parsers.py              HTML / PDFパーサー
scripts/history.py              過去大会の公式最終順位の抽出
scripts/audit_sources.py        PDF・別ドメインの確認資料作成
config/                        取得元・手動補正
docs/                          確認記録
reports/                       ローカルの検証結果（Git管理外）
.cache/                        取得原本（Git管理外）
.github/workflows/pages.yml     静的ファイルの公開
```

写真や公式記事全文は転載せず、選手名・大会名・日程等の情報と原本リンクを整理します。JBV・JVA・各大会主催者とは関係のない非公式サイトです。
