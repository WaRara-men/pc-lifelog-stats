# PC Lifelog Stats

ActivityWatchのローカルAPIから、PCとAndroidの使用ログを読み取り専用で集計するWindows向けダッシュボードです。

個人のActivityWatchログや`.env`は含めません。このリポジトリはアプリ本体だけを公開するためのものです。

## Features

- 今日の合計使用時間
- 直近1日、7日、14日、30日の合計・平均・中央値・最大
- 月間カレンダーのヒート表示
- アプリ別使用時間
- ウィンドウタイトル別使用時間
- 日別推移
- 時間帯ヒート
- 期間インサイト
- 最近の記録
- Androidバケット同期後の自動合算

## 起動

`start_dashboard.bat` をダブルクリックします。

ブラウザが開かない場合は、手動で以下を開いてください。

```text
http://127.0.0.1:8765
```

## Windows検索から起動

`install_start_menu_shortcut.ps1` を実行すると、スタートメニューに `PC Lifelog Stats` が登録されます。

登録後は、Windowsキーを押して `PC` または `lifelog` と検索すれば起動できます。デスクトップには何も増やしません。

## 注意

- ActivityWatchが起動していて、`http://localhost:5600/api/0` にアクセスできる必要があります。
- Android側のバケットがPCに同期されると、自動で `Android:` として合算されます。
- データは変更しません。ActivityWatch APIを読み取るだけです。
- GitHubにはActivityWatchの実ログ、CSV、JSONL、DB、`.env`を載せないでください。
