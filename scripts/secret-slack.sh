#!/bin/zsh
# クリップボードの SLACK_USER_TOKEN を yorimichi repo の Secret に設定する。
set -e
v=$(pbpaste | tr -d '[:space:]')
if [[ "$v" != xoxp-* ]]; then
  echo "❌ クリップボードが Slack の User Token ではありません（xoxp- で始まっていない）。"
  echo "   gmail-digest の OAuth & Permissions 画面で User OAuth Token を Copy してから再実行してください。"
  exit 1
fi
echo "確認: ${v:0:8}... （${#v}文字）→ SLACK_USER_TOKEN"
printf '%s' "$v" | gh secret set SLACK_USER_TOKEN -R mediiiiium/yorimichi
echo "✅ 設定完了"
