#!/usr/bin/env python3
"""発行結果を Pushover（iPhone）に通知する。tony の scripts/notify.py と同じ流儀:
成功でも失敗でも必ず1本送る（無通知＝成功、という解釈を成立させないため）。
Pushover に送れなかったら exit 1 で workflow を赤くし、GitHub アプリの通知で気づく
（Pushover が死んでいることを Pushover では知らせられない）。

優先度は tony の呼び方に合わせる: 発行できた号は「あとで」(-1。通知センターに静かに積む)、
発行できなかった週は仕組みの警告なので「通常」(0)。
★token / user は例外メッセージにも出さない（Actions のログに残るため）。"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.pushover.net/1/messages.json"
MAX_MESSAGE = 1024   # Pushover の message 上限
LATER, NORMAL = -1, 0


def send(message, title, priority, url="", url_title=""):
    token = os.environ.get("PUSHOVER_TOKEN", "").strip()
    user = os.environ.get("PUSHOVER_USER", "").strip()
    if not token or not user:
        raise RuntimeError("PUSHOVER_TOKEN / PUSHOVER_USER が無い（GitHub Secrets を確認）")
    payload = {"token": token, "user": user, "title": title, "priority": str(priority),
               "message": message[:MAX_MESSAGE]}
    if url:
        payload["url"] = url
        payload["url_title"] = url_title
    req = urllib.request.Request(API, data=urllib.parse.urlencode(payload).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        # 400 の本文に理由（user key が不正、など）が入っている。キーそのものは返ってこない
        raise RuntimeError(f"Pushover HTTP {e.code}: {e.read().decode()[:500]}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Pushover に届かない: {type(e).__name__}") from None
    if body.get("status") != 1:
        raise RuntimeError(f"Pushover が受け付けなかった: {body.get('errors') or body.get('status')}")


def build(result, run_url):
    """(title, message, priority, url, url_title) を返す。"""
    if result.get("ok"):
        message = f"今週の寄り道: {result['topic']} —「{result['title']}」\n{result['lead']}"
        notes = list(result.get("warnings") or [])
        if result.get("dropped_videos"):
            notes.append(f"実在確認できなかった動画 {len(result['dropped_videos'])} 本を誌面から外しました")
        if notes:
            # 注記は本文が上限で切られても残るよう、先に長さを空けておく
            tail = "\n（" + " / ".join(notes) + "）"
            message = message[:MAX_MESSAGE - len(tail)] + tail
        return (f"📖 Tony Magazine 第{result['no']}号", message, LATER,
                result["url"], "📰 読む")
    reason = result.get("reason", "原稿の生成に失敗（claude -p が異常終了）")
    return ("⚠️ Tony Magazine 今週号を発行できませんでした", f"理由: {reason}", NORMAL,
            run_url, "実行ログ")


def main():
    run_url = "{}/{}/actions/runs/{}".format(
        os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
        os.environ.get("GITHUB_REPOSITORY", ""),
        os.environ.get("GITHUB_RUN_ID", ""))

    result = {}
    if os.path.exists("build_result.json"):
        result = json.load(open("build_result.json", encoding="utf-8"))

    title, message, priority, url, url_title = build(result, run_url)
    try:
        send(message, title, priority, url, url_title)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"通知完了: {title}（{len(message)}文字）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
