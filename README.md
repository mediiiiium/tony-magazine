# Tony Magazine

毎週日曜の朝、興味を「広げる」か「深める」テーマをひとつ深掘りして届ける、
読者ひとりのための週刊個人誌。GitHub Pages で発行し、Slack DM に届く。
特集は毎号1テーマ（日常圏の深掘りも未知ジャンルへの寄り道も可。日英ソースをミックスし海外ソースは翻訳して紹介・YouTube動画つき）、
巻末に AI / クラフトビール / 海外フットボール / エンタメ / SNSバズ の「今週のトピックス」。

📰 誌面: https://mediiiiium.github.io/tony-magazine/

## 仕組み

```
毎週日曜 6:00 JST (GitHub Actions cron)
  → claude -p（サブスク枠 CLAUDE_CODE_OAUTH_TOKEN / WebSearch・WebFetch のみ許可）
     prompts/editorial.md の編集方針 + 過去号一覧 を読んでテーマ選定 → Web調査 → 執筆
  → scripts/build_issue.py が検品・サニタイズして誌面を組む
     - script/iframe/イベント属性は機械除去（動画は data-yt から生成）
     - YouTube 動画IDはサムネイル実在確認。無い動画は落とす（ID捏造対策）
     - ソース欄が無い号は不合格
  → docs/ に commit & push（= GitHub Pages に発行）
  → Slack 自分DM に「第N号 + リンク」通知。末尾マーカー [magazine-ok]
```

tony（~/tony）と同じ流儀: **LLM が失敗しても黙らない**。発行できなかった週も
必ず Slack に「発行できなかった + 理由」を投稿する（無通知＝成功と解釈させない）。

## リポジトリ構成

| パス | 中身 |
|---|---|
| `prompts/editorial.md` | 編集方針（テーマ選定ルール・禁止領域・出力形式）。誌の性格はここで変える |
| `scripts/make_prompt.py` | 編集方針+過去号一覧からプロンプトを組む |
| `scripts/build_issue.py` | 検品・サニタイズ・誌面組み・目次再生成 |
| `scripts/notify_slack.py` | Slack DM 通知（成功時のみ `[magazine-ok]`） |
| `templates/` | 号・目次の HTML テンプレート |
| `docs/` | GitHub Pages 公開ルート。`issues/*.html` が各号、`issues.json` が既刊台帳 |

## 必要な Secrets（Actions）

- `CLAUDE_CODE_OAUTH_TOKEN` — `claude setup-token` で発行（サブスク枠。API課金なし）
- `SLACK_USER_TOKEN` — 私用WS「103」の gmail-digest App の User Token（tony と共用）

## 手動発行

Actions → Magazine → Run workflow。同日2号目は台帳チェックで弾かれる（1日1号）。
