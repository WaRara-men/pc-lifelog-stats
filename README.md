# PC Lifelog Stats

自分がPCをどれだけ見ているのかを、ActivityWatchのログから見える化するローカルダッシュボードです。

今日の使用時間、アプリ別ランキング、時間帯ヒート、月間カレンダーをまとめて表示します。Android版ActivityWatchのログをPCに同期すれば、スマホ利用も同じ画面で合算できます。

![Dashboard preview](https://raw.githubusercontent.com/WaRara-men/pc-lifelog-stats/main/docs/dashboard-preview.svg)

## What It Shows

- 今日どれだけPC/Androidを使ったか
- 直近1日、7日、14日、30日の合計・平均・中央値・最大
- 使用時間で色が濃くなる月間カレンダー
- アプリ別の使用時間ランキング
- ウィンドウタイトル別の使用時間ランキング
- 何時台によく使っているかが分かる時間帯ヒート
- 最近のアクティビティ一覧
- Androidログ同期後の自動合算

## Why

ActivityWatchは強力ですが、「とりあえず今日どれだけ見たか」「今月の濃い日がどこか」を一目で見るには少し距離があります。

このアプリは、細かいログを読むためではなく、自分の生活リズムをぱっと掴むための画面です。使いすぎを責めるより、まず自分の時間の形を見えるようにすることを目指しています。

## Requirements

- Windows 11
- Python 3.12+
- ActivityWatch desktop app
- ActivityWatch local API: `http://localhost:5600/api/0`

## Quick Start

1. ActivityWatchを起動します。
2. このリポジトリをダウンロードまたはcloneします。
3. `start_dashboard.bat` をダブルクリックします。
4. ブラウザで `http://127.0.0.1:8765` が開きます。

```powershell
git clone https://github.com/WaRara-men/pc-lifelog-stats.git
cd pc-lifelog-stats
.\start_dashboard.bat
```

## Start From Windows Search

デスクトップにショートカットを増やしたくない場合は、スタートメニューにだけ登録できます。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_start_menu_shortcut.ps1
```

登録後は、Windowsキーを押して `lifelog` または `PC` と検索すると **PC Lifelog Stats** が出ます。

## Data Safety

このアプリはActivityWatchのローカルAPIを読み取るだけです。ActivityWatchのデータを書き換えません。

このリポジトリには、個人のActivityWatchログ、CSV、JSONL、DB、`.env`、秘密鍵、トークンを含めない方針です。`.gitignore` でもそれらを除外しています。

## Android Logs

Android版ActivityWatchのバケットがPC側に同期されると、画面内で自動的に `Android:` として集計されます。

まだ同期されていない場合は、ダッシュボード上に「AndroidのバケットはまだPC側に見えていません」と表示されます。

AndroidアプリにExportが無い場合は、ADBでスマホ内のActivityWatch APIをPCへ橋渡しできます。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\connect_android_adb.ps1
```

このスクリプトは、Android端末の `localhost:5600` をPCの `http://127.0.0.1:5601` に転送します。転送後、ダッシュボードはAndroidバケットを自動で読みます。

Export JSONがある場合は、ローカルに取り込めます。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\import_android_export.ps1 "C:\path\to\aw-buckets-export.json"
```

取り込んだデータは `local_data/android_events.json` に保存されます。`local_data/` はGit管理外です。

同じExportファイルを継続して使う場合は、自動取り込み対象として登録できます。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\watch_android_export.ps1 "C:\path\to\aw-buckets-export.json"
```

登録後は、そのJSONの更新日時やサイズが変わると、ダッシュボードの更新時に自動で再取り込みされます。

## Project Status

Personal project.  
今はローカル利用を前提にした軽量版です。

今後の候補:

- カテゴリ分類
- 週/月レポート
- CSVエクスポート
- より細かいAndroidアプリ分析
- 使いすぎアラート
