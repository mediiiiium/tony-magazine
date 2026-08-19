#!/usr/bin/env python3
"""発行結果を Slack 自分DMへ通知する。tony の brief/report と同じ流儀:
成功でも失敗でも必ず投稿し、成功時だけ末尾に [magazine-ok] マーカーを置く
（無通知＝成功、という解釈を成立させないため）。"""
import json
import os
import sys
import urllib.parse
import urllib.request

MARKER = "[magazine-ok]"


def slack(method, params, token):
    req = urllib.request.Request(
        "https://slack.com/api/" + method,
        data=urllib.parse.urlencode(params).encode(),
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        data = json.loads(res.read().decode())
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} 失敗: {data.get('error')}")
    return data


def main():
    token = os.environ.get("SLACK_USER_TOKEN", "").strip()
    if not token:
        print("SLACK_USER_TOKEN が未設定", file=sys.stderr)
        return 1

    run_url = "{}/{}/actions/runs/{}".format(
        os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
        os.environ.get("GITHUB_REPOSITORY", ""),
        os.environ.get("GITHUB_RUN_ID", ""))

    result = {}
    if os.path.exists("build_result.json"):
        result = json.load(open("build_result.json", encoding="utf-8"))

    if result.get("ok"):
        text = (f"📖 *ヨリミチ 第{result['no']}号* が届きました\n"
                f"今週の寄り道: *{result['topic']}* —「{result['title']}」\n"
                f"{result['lead']}\n"
                f"<{result['url']}|📰 読む>\n\n{MARKER}")
        notes = list(result.get("warnings") or [])
        if result.get("dropped_videos"):
            notes.append(f"実在確認できなかった動画 {len(result['dropped_videos'])} 本を誌面から外しました")
        if notes:
            text += "\n_（" + " / ".join(notes) + "）_"
    else:
        reason = result.get("reason", "原稿の生成に失敗（claude -p が異常終了）")
        text = (f"⚠️ *ヨリミチ 今週号を発行できませんでした*\n"
                f"理由: {reason}\n<{run_url}|実行ログ>")

    auth = slack("auth.test", {}, token)
    ch = slack("conversations.open", {"users": auth["user_id"]}, token)["channel"]["id"]
    slack("chat.postMessage", {"channel": ch, "text": text}, token)
    print(f"通知完了: {len(text)}文字", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
