# PC Lifelog Stats

Windows PCとAndroidスマホのスクリーンタイムを、ひとつのローカル画面で見るためのライフログダッシュボードです。

PC側はActivityWatch、Android側は同梱の **PC Lifelog Sender** から取得します。スマホは初回だけPC画面のQRを読み取ればOK。以後はWi-Fi接続時に15分ごとに自動送信され、PCのカレンダー、ランキング、時間帯ヒートに合算されます。

**Highlights**

- PCとAndroidの使用時間を同じ画面で合算
- 初回だけQRペアリング、その後はQR不要
- Androidは15分ごとにWi-Fiで自動送信
- 接続状態、最終受信時刻、今日のスマホ使用時間をダッシュボードに表示
- 個人ログとtokenは `local_data/` に保存し、Gitには載せないlocal-first設計

![Dashboard preview](https://raw.githubusercontent.com/WaRara-men/pc-lifelog-stats/main/docs/dashboard-preview.svg)

## What It Shows

- 今日どれだけPC/Androidを使ったか
- 直近1日、7日、14日、30日の合計・平均・中央値・最大
- 使用時間で色が濃くなる月間カレンダー
- アプリ別の使用時間ランキング
- ウィンドウタイトル別の使用時間ランキング
- 何時台によく使っているかが分かる時間帯ヒート
- 最近のアクティビティ一覧
- Android Senderの接続状態と最終受信

## Android Companion

このリポジトリには、Android端末からPCへスクリーンタイムを送る companion app が入っています。

PC側のダッシュボードで `Android連携` のQRを表示し、Androidアプリ **PC Lifelog Sender** で一度だけ読み取ります。スマホ側に接続先とtokenが保存されるので、次回以降はQRを読み直す必要がありません。

自動同期はWi-Fiなどの非従量課金ネットワークで動く設計です。機内モードや外出中で送れなかった分は端末内に残り、次に送れるタイミングでまとめてPCへ送信します。

## Why

ActivityWatchは強力ですが、「とりあえず今日どれだけ見たか」「今月の濃い日がどこか」を一目で見るには少し距離があります。

このアプリは、細かいログを読むためだけではなく、自分の生活リズムをぱっと掴むための画面です。PCとスマホを別々に眺めるのではなく、「今日、自分は画面とどう付き合っていたか」をひと目で見えるようにすることを目指しています。

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

## Pair Android by QR

Android companion appを使う場合は、PC側にQRを表示して初回だけ読み取ります。読み取り後、スマホ側に接続先とtokenが保存されるため、次回以降QRは不要です。

PC側の受信ポートをLAN内だけ許可します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\enable_android_sender_firewall.ps1
```

ダッシュボードを開き、`Android連携` の `接続QRを表示` を押します。QRには以下が入ります。

```json
{
  "name": "PC Lifelog Stats",
  "server": "http://<PCのLAN IP>:8766",
  "token": "<local token>",
  "version": 1,
  "once": true
}
```

Android側はこの情報を保存し、以後は `POST /api/android/events` にtoken付きで送信します。

Androidアプリ本体は `android-sender/` にあります。Android Studioで開いて `app` モジュールをビルドします。現時点では個人利用向けのdebug APKとして扱っています。

ローカルでビルドしたdebug APKは以下に出ます。

```text
android-sender/app/build/outputs/apk/debug/app-debug.apk
```

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
