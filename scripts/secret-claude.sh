#!/bin/zsh
# クリップボードの CLAUDE_CODE_OAUTH_TOKEN を yorimichi repo の Secret に設定する。
# 値は画面に出さない（先頭と文字数だけ確認表示）。
set -e
v=$(pbpaste | tr -d '[:space:]')
if [[ "$v" != sk-ant-oat* ]]; then
  echo "❌ クリップボードが claude のトークンではありません（sk-ant-oat で始まっていない）。"
  echo "   ターミナルに表示されたトークンをコピーし直してから、もう一度このスクリプトを実行してください。"
  exit 1
fi
echo "確認: ${v:0:10}... （${#v}文字）→ CLAUDE_CODE_OAUTH_TOKEN"
printf '%s' "$v" | gh secret set CLAUDE_CODE_OAUTH_TOKEN -R mediiiiium/yorimichi
echo "✅ 設定完了"
