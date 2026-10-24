#!/usr/bin/env python3
"""連載「今週の若手」を、息子の Slack DM に送る（私用WS「103」。送り主は父のアカウント）。

中身は build_issue.py が build_result.json の "rookies" に入れたもの（検品済み・動画は実在確認済み）。
発行できなかった週や若手が揃わなかった週は、息子には何も送らない（失敗の知らせは父の Pushover だけ）。
送れたか・送らなかった理由は son_result.json に書き、notify.py が父への通知に一言添える。
★token は例外メッセージにも出さない（Actions のログに残るため）。"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def slack(method, params, token):
    req = urllib.request.Request(
        "https://slack.com/api/" + method,
        data=urllib.parse.urlencode(params).encode(),
        headers={"Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.loads(res.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Slack に届かない: {type(e).__name__}") from None
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} 失敗: {data.get('error')}")
    return data


def build(result):
    """息子に送る本文（Slack mrkdwn）。YouTube の URL は裸で置いて Slack にサムネイルを出させる。"""
    k = result["rookies"]
    lines = [f"⚽ *今週の注目の若手*（{result.get('date_ja', '')}）", "", f"*{k['head']}*", k["meta"]]
    if k.get("events"):
        lines.append("今週: " + " / ".join(k["events"]))
    if k.get("kid"):
        lines += ["", k["kid"]]
    lines.append("")
    for c in k["clips"]:
        lines.append(f"▶ {c['caption']}\nhttps://www.youtube.com/watch?v={c['vid']}")
    fav = k.get("fav")
    if fav:
        tail = f" <{fav['href']}|{fav['outlet'] or 'くわしく'}>" if fav.get("href") else ""
        lines += ["", f"💙❤️ *おまけ* {fav['text']}{tail}"]
    lines += ["", f"<{result['url']}|📊 グラフつきで見る（お父さんの雑誌）>"]
    return "\n".join(lines)


def main():
    result = {}
    if os.path.exists("build_result.json"):
        result = json.load(open("build_result.json", encoding="utf-8"))

    status = {"sent": False}
    if not result.get("ok"):
        status["reason"] = "号が発行できなかったので送っていません"
    elif not result.get("rookies"):
        status["reason"] = "今週の若手が組めなかったので送っていません"
    else:
        token = os.environ.get("SLACK_USER_TOKEN", "").strip()
        son = os.environ.get("SLACK_SON_USER_ID", "").strip()
        try:
            if not token or not son:
                raise RuntimeError("SLACK_USER_TOKEN / SLACK_SON_USER_ID が無い（GitHub Secrets を確認）")
            ch = slack("conversations.open", {"users": son}, token)["channel"]["id"]
            slack("chat.postMessage", {"channel": ch, "text": build(result)}, token)
            status = {"sent": True, "player": result["rookies"]["head"]}
        except RuntimeError as e:
            status["reason"] = str(e)

    json.dump(status, open("son_result.json", "w"), ensure_ascii=False)
    print(f"息子への Slack: {status}", file=sys.stderr)
    # ここでは落とさない。送れなかったことは父の Pushover に添える（notify.py）
    return 0


if __name__ == "__main__":
    sys.exit(main())
