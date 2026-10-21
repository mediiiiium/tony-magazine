#!/bin/zsh
# クリップボードの Pushover キーを tony-magazine repo の Secret に設定する。
# 使い方: secret-pushover.sh token  （アプリの API Token をコピーしてから）
#         secret-pushover.sh user   （ユーザーキーをコピーしてから）
# tony と同じキーを使う（Pushover の管理画面 https://pushover.net で確認できる）。
set -e
case "$1" in
  token) name=PUSHOVER_TOKEN ;;
  user)  name=PUSHOVER_USER ;;
  *) echo "使い方: $0 token|user"; exit 1 ;;
esac
v=$(pbpaste | tr -d '[:space:]')
if [[ ! "$v" =~ ^[A-Za-z0-9]{30}$ ]]; then
  echo "❌ クリップボードが Pushover のキーではありません（英数字30文字ではない: ${#v}文字）。"
  exit 1
fi
echo "確認: ${v:0:4}... （${#v}文字）→ $name"
printf '%s' "$v" | gh secret set "$name" -R mediiiiium/tony-magazine
echo "✅ 設定完了"
