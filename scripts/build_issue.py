#!/usr/bin/env python3
"""claude の出力（issue_raw.txt）を検品・サニタイズして誌面に組む。

公開ページになるので、LLM出力はそのまま信用しない:
- script/style/iframe/イベント属性は機械的に除去（動画は data-yt からこちらで埋め込みを生成）
- 動画IDは YouTube のサムネイルが実在するか HTTP で確認し、無い動画は落とす（ID捏造対策）
- ソース欄が無い号は不合格（このマガジンの必須要件）
失敗時は build_result.json に理由を書いて exit 1（通知ステップが拾う）。
"""
import html
import json
import os
import re
import sys
import urllib.request

RAW = "issue_raw.txt"
ALLOWED_ACCENT = re.compile(r"^#[0-9a-fA-F]{6}$")
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def fail(reason):
    json.dump({"ok": False, "reason": reason}, open("build_result.json", "w"), ensure_ascii=False)
    print(f"不合格: {reason}", file=sys.stderr)
    sys.exit(1)


def yt_exists(vid):
    try:
        req = urllib.request.Request(f"https://img.youtube.com/vi/{vid}/hqdefault.jpg", method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status == 200
    except Exception:
        return False


def sanitize(body):
    body = re.sub(r"(?is)<script.*?</script>", "", body)
    body = re.sub(r"(?is)<style.*?</style>", "", body)
    body = re.sub(r"(?is)<iframe[^>]*>.*?</iframe>", "", body)
    body = re.sub(r"(?is)<iframe[^>]*/?>", "", body)
    body = re.sub(r"""(?i)\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", "", body)
    body = re.sub(r"(?i)javascript\s*:", "", body)
    return body


def embed_videos(body):
    """<figure class="video" data-yt="ID">…</figure> を実在確認つきで iframe 化する。"""
    dropped = []

    def repl(m):
        tag = m.group(0)
        idm = re.search(r'data-yt="([^"]+)"', tag)
        cap = re.search(r"(?is)<figcaption>(.*?)</figcaption>", tag)
        caption = cap.group(1).strip() if cap else ""
        vid = idm.group(1).strip() if idm else ""
        if not YT_ID.match(vid) or not yt_exists(vid):
            dropped.append(vid or "(IDなし)")
            return ""
        return (
            f'<figure class="video"><div class="frame">'
            f'<iframe src="https://www.youtube-nocookie.com/embed/{vid}" '
            f'title="YouTube video" loading="lazy" allowfullscreen '
            f'allow="accelerometer; encrypted-media; picture-in-picture"></iframe></div>'
            f"<figcaption>{caption}"
            f' ｜ <a href="https://www.youtube.com/watch?v={vid}">YouTubeで見る</a></figcaption></figure>'
        )

    body = re.sub(r'(?is)<figure class="video"[^>]*>.*?</figure>', repl, body)
    return body, dropped


def main():
    if not os.path.exists(RAW) or os.path.getsize(RAW) == 0:
        fail("原稿がありません（claude -p 失敗）")
    raw = open(RAW, encoding="utf-8").read().strip()
    raw = re.sub(r"^```(html)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    m = re.search(r"(?s)<!--META\s*(\{.*?\})\s*META-->", raw)
    if not m:
        fail("META ブロックが見つかりません")
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        fail(f"META がJSONとして読めません: {e}")
    for k in ("topic", "title", "lead", "emoji", "accent"):
        if not meta.get(k):
            fail(f"META に {k} がありません")
    if not ALLOWED_ACCENT.match(meta["accent"]):
        meta["accent"] = "#8a6d1f"

    body = raw[m.end():].strip()
    body = sanitize(body)
    body, dropped = embed_videos(body)
    if len(body) < 1500:
        fail(f"本文が短すぎます（{len(body)}文字）")
    if 'class="sources"' not in body or "<a href=" not in body:
        fail("ソース欄がありません（この誌の必須要件）")
    warnings = []
    if 'class="topics"' not in body:
        warnings.append("今週のトピックス欄がありません")

    issues = json.load(open("docs/issues.json", encoding="utf-8"))
    slug = os.environ.get("DATE_SLUG")
    date_ja = os.environ.get("DATE_JA", slug)
    if not slug:
        fail("DATE_SLUG が未設定")
    if any(i["date"] == slug for i in issues):
        fail(f"{slug} の号は発行済みです")
    no = len(issues) + 1

    tpl = open("templates/issue.html", encoding="utf-8").read()
    esc = lambda s: html.escape(str(s), quote=True)
    page = (tpl.replace("{{TITLE}}", esc(meta["title"]))
               .replace("{{LEAD}}", esc(meta["lead"]))
               .replace("{{TOPIC}}", esc(meta["topic"]))
               .replace("{{EMOJI}}", esc(meta["emoji"]))
               .replace("{{ACCENT}}", meta["accent"])
               .replace("{{ISSUE_NO}}", str(no))
               .replace("{{DATE_JA}}", esc(date_ja))
               .replace("{{BODY}}", body))
    open(f"docs/issues/{slug}.html", "w", encoding="utf-8").write(page)

    issues.insert(0, {"no": no, "date": slug, "date_ja": date_ja, "topic": meta["topic"],
                      "title": meta["title"], "lead": meta["lead"],
                      "emoji": meta["emoji"], "accent": meta["accent"]})
    json.dump(issues, open("docs/issues.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    cards = "\n".join(
        f'    <a class="card" href="issues/{i["date"]}.html" style="--accent:{i["accent"]}">\n'
        f'      <span class="card-emoji">{esc(i["emoji"])}</span>\n'
        f'      <span class="card-no">第{i["no"]}号 · {esc(i["date_ja"])} · {esc(i["topic"])}</span>\n'
        f'      <h2>{esc(i["title"])}</h2>\n'
        f'      <p>{esc(i["lead"][:80])}</p>\n'
        f'    </a>' for i in issues)
    idx = open("templates/index.html", encoding="utf-8").read()
    open("docs/index.html", "w", encoding="utf-8").write(
        idx.replace("{{CARDS}}", cards).replace("{{COUNT}}", str(len(issues))))

    url = f"https://mediiiiium.github.io/yorimichi/issues/{slug}.html"
    json.dump({"ok": True, "no": no, "title": meta["title"], "topic": meta["topic"],
               "lead": meta["lead"], "url": url, "dropped_videos": dropped,
               "warnings": warnings},
              open("build_result.json", "w"), ensure_ascii=False)
    print(f"第{no}号「{meta['title']}」を組みました → docs/issues/{slug}.html")
    if dropped:
        print(f"⚠️ 実在確認できず落とした動画: {dropped}", file=sys.stderr)


if __name__ == "__main__":
    main()
