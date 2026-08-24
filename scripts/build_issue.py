#!/usr/bin/env python3
"""claude の出力（issue_raw.txt）を検品・サニタイズして誌面に組む。

公開ページになるので、LLM出力はそのまま信用しない:
- script/style/iframe/イベント属性は機械的に除去（動画は data-yt からこちらで埋め込みを生成）
- 動画IDは YouTube のサムネイルが実在するか HTTP で確認し、無い動画は落とす（ID捏造対策）
- ソース欄が無い号は不合格（このマガジンの必須要件）
失敗時は build_result.json に理由を書いて exit 1（通知ステップが拾う）。

誌面の組み方:
- 扉は全面1枚。docs/img/<slug>.(webp|jpg) があればそれ、無ければ題を一字置く（glyph）
- 巻末トピックスは大きさの違うカードのモザイクに組み替える
- 英語ソースは日本語ダイジェストごと専用レーンに立てる（原文を開かなくて済むように）
"""
import datetime
import html
import json
import os
import re
import sys
import urllib.request

RAW = "issue_raw.txt"
ALLOWED_ACCENT = re.compile(r"^#[0-9a-fA-F]{6}$")
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
IMG_DIR = "docs/img"
# LLM の生原稿の保管庫。誌面デザインを変えたとき、ここから過去号を組み直す。
ARCHIVE_DIR = "archive"

# トピックスの5分野の地色（この順・固定。プロンプト側と対応）
TINT = {
    "AI": "#16212f",
    "クラフトビール": "#6d4413",
    "海外フットボール": "#173023",
    "エンタメ": "#331a27",
    "SNSバズ": "#e9e1ce",   # ここだけ明るいので文字を反転する（.light）
}
LIGHT_TINTS = {"#e9e1ce"}
DEFAULT_TINT = "#22201c"

# 「今週のトピックス」は速報の欄。発行日からこの日数より前の項目は載せない。
# 1日ぶん甘いのは、報じられた日と現地の日付がずれることがあるため。
FRESH_DAYS = 8


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


def card_lead(text, limit=80):
    """表紙カードの抜粋。80字でぶつ切りにすると文の途中で切れるので、句点まで戻す。
       句点が手前すぎる（半分未満）ときだけ … で締める。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    stop = head.rfind("。")
    if stop >= limit // 2:
        return head[:stop + 1]
    return head.rstrip("、（(「 ") + "…"


# ─────────────────────────────────────────────────────────────
# 英語ソース: 原文を開かなくて済むように、日本語ダイジェストごと1枚に立てる
# ─────────────────────────────────────────────────────────────
def en_sources(body):
    """<article class="en-src" data-words="N"> を専用レーンにまとめ、バッジと注記を付ける。"""
    arts = re.findall(r'(?is)<article class="en-src"[^>]*>.*?</article>', body)
    if not arts:
        return body, 0
    for a in arts:
        body = body.replace(a, "", 1)

    built = []
    for a in arts:
        wm = re.search(r'data-words="(\d+)"', a)
        host = re.search(r'<h3>\s*<a href="https?://([^/"]+)', a)
        foot = []
        if host:
            foot.append(html.escape(host.group(1).replace("www.", "")))
        if wm:
            n = int(wm.group(1))
            foot.append(f"英語 ・ 約{n:,}語 ・ 読了 {max(1, round(n / 250))}分")
        foot.append("ダイジェストは Claude が原文から作成")
        a = re.sub(r'\sdata-words="\d+"', "", a)
        a = a.replace(">", '>\n<p class="en-ja en-tag"><span class="en-flag">EN</span>英語ソース</p>', 1)
        a = a.replace("</article>", f'<p class="foot">{" ／ ".join(foot)}</p></article>')
        built.append(a)

    lane = ('<div class="en-lane">\n'
            '<p class="en-lane-note"><span class="en-flag">EN</span>'
            '英語のソースには、Claude が原文を読んで書いた日本語ダイジェストを付けています。'
            '原文を開かなくても中身が分かります。</p>\n' + "\n".join(built) + "\n</div>\n")
    # ソース欄の <h2> 直後に差し込む
    body = re.sub(r'(?is)(<section class="sources">\s*<h2>.*?</h2>)', r"\1\n" + lane.replace("\\", "\\\\"), body, count=1)
    return body, len(arts)


# ─────────────────────────────────────────────────────────────
# 巻末トピックス: 大きさの違うカードのモザイクに組み替える
# ─────────────────────────────────────────────────────────────
def spans_for(items):
    """1行が必ず6カラムになるように割り当てる。乱数は使わず、見出しの長さで決める。"""
    n = len(items)
    out = []
    i = 0
    while i < n:
        rest = n - i
        if rest == 1:
            out.append(6); i += 1
        elif rest == 3:
            out += [2, 2, 2]; i += 3
        else:
            a, b = len(items[i]["head"]), len(items[i + 1]["head"])
            if a > b * 1.15:
                out += [4, 2]
            elif b > a * 1.15:
                out += [2, 4]
            else:
                out += [3, 3]
            i += 2
    return out


def parse_topic_li(li, attrs=""):
    """LLM が書いた <li> を、見出し / 補足 / リンク / ダイジェスト / 動画 / 日付 に分解する。"""
    md = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', attrs or "")
    vid = ""
    m = re.search(r'(?is)<span class="yt"[^>]*data-yt="([^"]+)"[^>]*>\s*</span>', li)
    if m:
        vid = m.group(1).strip()
        li = li.replace(m.group(0), "")
    digest = ""
    m = re.search(r'(?is)<div class="digest"[^>]*>.*?</div>', li)
    if m:
        digest = m.group(0)
        li = li.replace(digest, "")
    href = text = ""
    links = re.findall(r'(?is)<a href="([^"]+)"[^>]*>(.*?)</a>', li)
    if links:
        href, text = links[-1]
        li = re.sub(r'(?is)<a href="[^"]+"[^>]*>.*?</a>\s*$', "", li.strip())
    plain = re.sub(r"(?is)<[^>]+>", "", li).strip()
    plain = re.sub(r"\s+", " ", plain)
    head, mark, sub = plain.partition("。")
    if not mark and len(plain) > 46:
        # 句点が無い長い項目は、読点で切って見出しと補足に分ける（丸ごと見出しにしない）
        cut = plain.rfind("、", 0, 46)
        if cut > 12:
            head, sub = plain[:cut], plain[cut + 1:]
    return {"head": (head + "。") if mark else head, "sub": sub.strip(),
            "href": href.strip(), "outlet": re.sub(r"(?is)<[^>]+>", "", text).strip(),
            "digest": digest, "vid": vid, "date": md.group(1) if md else ""}


def build_digest(digest_html, words):
    """LLM の <div class="digest"> を、畳める <details> に変える。"""
    inner = re.sub(r'(?is)^<div class="digest"[^>]*>|</div>$', "", digest_html).strip()
    by = "原文（英語）を Claude が読んで作成"
    if words:
        by = f"原文（英語・約{words:,}語）を Claude が読んで作成"
    return ('<details class="digest"><summary>日本語ダイジェスト</summary>'
            f'{inner}<p class="by">{by}</p></details>')


def drop_stale(items, slug):
    """発行日から見て古すぎる項目を落とす。日付が読めない項目は落とさず数だけ返す。"""
    try:
        pub = datetime.date.fromisoformat(slug or "")
    except ValueError:
        return items, [], 0
    kept, stale, nodate = [], [], 0
    for it in items:
        try:
            age = (pub - datetime.date.fromisoformat(it["date"])).days
        except ValueError:
            nodate += 1
            kept.append(it)
            continue
        if -1 <= age <= FRESH_DAYS:
            kept.append(it)
        else:
            stale.append(f'{it["head"][:20]}（{it["date"]}）')
    return kept, stale, nodate


def mosaicize(body, slug=""):
    """<div class="topic-group"> の羅列を、カードのモザイクに組み替える。"""
    sec = re.search(r'(?is)<section class="topics">(.*?)</section>', body)
    if not sec:
        return body, [], 0, [], [], 0
    inner = sec.group(1)
    dropped, videos, cats = [], 0, []
    stale, nodate = [], 0
    cards = []
    for grp in re.findall(r'(?is)<div class="topic-group">(.*?)</div>\s*(?=<div class="topic-group">|$)', inner):
        cat = re.search(r"(?is)<h3>(.*?)</h3>", grp)
        cat = re.sub(r"(?is)<[^>]+>", "", cat.group(1)).strip() if cat else ""
        # ダイジェスト（中に <ul class="figs"><li> を持つ）を先に退避しないと、
        # 中の <li> まで項目として拾ってしまう
        stash = []

        def hide(m):
            stash.append(m.group(0))
            return f"\x00D{len(stash) - 1}\x00"

        grp = re.sub(r'(?is)<div class="digest"[^>]*>.*?</div>', hide, grp)
        lis = [(a, re.sub(r"\x00D(\d+)\x00", lambda m: stash[int(m.group(1))], x))
               for a, x in re.findall(r"(?is)<li\b([^>]*)>(.*?)</li>", grp)]
        items = [parse_topic_li(x, a) for a, x in lis]
        items, gs, gn = drop_stale(items, slug)
        stale += gs
        nodate += gn
        if not items:
            continue
        cats.append(cat)
        for it, sp in zip(items, spans_for(items)):
            tint = TINT.get(cat, DEFAULT_TINT)
            cls = ["card"]
            if sp >= 4:
                cls.append("wide")
            if tint in LIGHT_TINTS:
                cls.append("light")
            if it["digest"]:
                cls.append("en")
            wm = re.search(r'data-words="(\d+)"', it["digest"])
            parts = [f'<span class="cat">{html.escape(cat)}']
            if it["digest"]:
                parts.append('<span class="en-flag">EN</span>')
            parts.append("</span>")
            head = html.escape(it["head"])
            parts.append(f'<h3><a href="{html.escape(it["href"], quote=True)}">{head}</a></h3>'
                         if it["href"] else f"<h3>{head}</h3>")
            if it["sub"]:
                parts.append(f'<p class="sub">{html.escape(it["sub"])}</p>')
            if it["vid"]:
                if YT_ID.match(it["vid"]) and yt_exists(it["vid"]):
                    parts.append(
                        f'<a class="yt-thumb" href="https://www.youtube.com/watch?v={it["vid"]}">'
                        f'<img src="https://img.youtube.com/vi/{it["vid"]}/hqdefault.jpg" alt="" loading="lazy">'
                        f"<span>YouTubeで見る</span></a>")
                    videos += 1
                else:
                    dropped.append(it["vid"] or "(IDなし)")
            if it["digest"]:
                parts.append(build_digest(it["digest"], int(wm.group(1)) if wm else 0))
            if it["outlet"]:
                parts.append(f'<span class="outlet">{html.escape(it["outlet"])}</span>')
            cards.append(f'<article class="{" ".join(cls)}" style="grid-column:span {sp};--tint:{tint}"'
                         f' data-mark="{html.escape(cat[:1])}">' + "".join(parts) + "</article>")

    if not cards:
        return body, dropped, videos, cats, stale, nodate
    new = ('<section class="topics"><h2>今週のトピックス</h2>\n<div class="mosaic">\n'
           + "\n".join(cards) + "\n</div></section>")
    return body[:sec.start()] + new + body[sec.end():], dropped, videos, cats, stale, nodate


# ─────────────────────────────────────────────────────────────
# 扉（全面1枚 / 写真が無ければ題を一字）
# ─────────────────────────────────────────────────────────────
def hero_for(slug, meta):
    """docs/img/<slug>.(webp|jpg|png) があれば全面写真、無ければ glyph。
       クレジットは docs/img/<slug>.json の {"credit_html": "...", "alt": "..."} から。"""
    for ext in ("webp", "jpg", "jpeg", "png"):
        path = f"{IMG_DIR}/{slug}.{ext}"
        if os.path.exists(path):
            credit = ""
            side = f"{IMG_DIR}/{slug}.json"
            if os.path.exists(side):
                try:
                    credit = json.load(open(side, encoding="utf-8")).get("credit_html", "")
                except Exception:
                    credit = ""
            return {
                "file": f"{slug}.{ext}",
                "class": "",
                "style": f' style="background-image:url(../img/{slug}.{ext})"',
                "glyph": "",
                "credit": f'  <p class="credit">{credit}</p>' if credit else "",
                "credit_line": ("<br>扉の図版: " + re.sub(r"(?is)<[^>]+>", "",
                                 re.sub(r"(?i)<br\s*/?>", " ／ ", credit))) if credit else "",
                "photo": True,
            }
    g = (meta.get("glyph") or meta.get("topic") or "誌")[:2]
    char = html.escape(g[0]) + (f"<em>{html.escape(g[1])}</em>" if len(g) > 1 else "")
    return {"file": "", "class": " glyph", "style": "",
            "glyph": f'  <div class="char">{char}</div>',
            "credit": "", "credit_line": "", "photo": False}


def main():
    slug = os.environ.get("DATE_SLUG")
    if not slug:
        fail("DATE_SLUG が未設定")
    date_ja = os.environ.get("DATE_JA", slug)
    # REBUILD=1 なら新規発行ではなく、保管してある生原稿からの組み直し
    rebuild = os.environ.get("REBUILD") == "1"
    src = f"{ARCHIVE_DIR}/{slug}.txt" if rebuild else RAW
    if not os.path.exists(src) or os.path.getsize(src) == 0:
        fail(f"生原稿がありません（{src}）" if rebuild else "原稿がありません（claude -p 失敗）")
    raw = open(src, encoding="utf-8").read().strip()
    raw = re.sub(r"^```(html)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # 検品より先に保存する。組版で弾かれた号でも、何を書いてきたかは残す
    if not rebuild:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        open(f"{ARCHIVE_DIR}/{slug}.txt", "w", encoding="utf-8").write(raw + "\n")

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

    issues = json.load(open("docs/issues.json", encoding="utf-8"))
    prev = next((i for i in issues if i["date"] == slug), None)
    if prev and not rebuild:
        fail(f"{slug} の号は発行済みです")
    if rebuild and not prev:
        fail(f"{slug} は台帳にない号です（組み直せません）")
    no = prev["no"] if prev else len(issues) + 1        # 号数は振り直さない
    date_ja = prev["date_ja"] if prev else date_ja

    warnings = []
    body, n_en = en_sources(body)
    if not n_en:
        warnings.append("英語ソースが1件もありません（日英ミックスが方針）")
    if 'class="topics"' not in body:
        warnings.append("今週のトピックス欄がありません")
    body, t_dropped, t_videos, t_cats, t_stale, t_nodate = mosaicize(body, slug)
    dropped += t_dropped
    missing = [c for c in TINT if c not in t_cats]
    if t_cats and missing:
        warnings.append("トピックスに分野が足りません: " + " / ".join(missing))
    if t_stale:
        warnings.append(f"今週のものでないトピックスを{len(t_stale)}件落としました: "
                        + " / ".join(t_stale))
    if t_nodate:
        warnings.append(f"日付(data-date)の無いトピックスが{t_nodate}件（速報性を検品できていません）")
    # トピックスは本文（38rem）の外に出す。カードのモザイクは70remで組むため
    topics = ""
    mt = re.search(r'(?is)<section class="topics">.*?</section>', body)
    if mt:
        topics = mt.group(0)
        body = body[:mt.start()] + body[mt.end():]

    hero = hero_for(slug, meta)
    if not hero["photo"]:
        warnings.append("扉の写真がないため、題を一字置く扉になりました")

    tpl = open("templates/issue.html", encoding="utf-8").read()
    esc = lambda s: html.escape(str(s), quote=True)
    page = (tpl.replace("{{TITLE}}", esc(meta["title"]))
               .replace("{{LEAD}}", esc(meta["lead"]))
               .replace("{{TOPIC}}", esc(meta["topic"]))
               .replace("{{EMOJI}}", esc(meta["emoji"]))
               .replace("{{ACCENT}}", meta["accent"])
               .replace("{{ISSUE_NO}}", str(no))
               .replace("{{DATE_JA}}", esc(date_ja))
               .replace("{{HERO_CLASS}}", hero["class"])
               .replace("{{HERO_STYLE}}", hero["style"])
               .replace("{{HERO_GLYPH}}", hero["glyph"])
               .replace("{{HERO_CREDIT}}", hero["credit"])
               .replace("{{CREDIT_LINE}}", hero["credit_line"])
               .replace("{{TOPICS}}", topics)
               .replace("{{BODY}}", body))
    open(f"docs/issues/{slug}.html", "w", encoding="utf-8").write(page)

    entry = {"no": no, "date": slug, "date_ja": date_ja, "topic": meta["topic"],
             "title": meta["title"], "lead": meta["lead"], "emoji": meta["emoji"],
             "accent": meta["accent"], "glyph": (meta.get("glyph") or meta["topic"])[:2],
             "hero": hero["file"]}
    if prev:
        issues[issues.index(prev)] = entry
    else:
        issues.insert(0, entry)
    json.dump(issues, open("docs/issues.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    write_cover(issues)

    url = f"https://mediiiiium.github.io/tony-magazine/issues/{slug}.html"
    json.dump({"ok": True, "no": no, "title": meta["title"], "topic": meta["topic"],
               "lead": meta["lead"], "url": url, "dropped_videos": dropped,
               "en_sources": n_en, "topic_videos": t_videos, "warnings": warnings},
              open("build_result.json", "w"), ensure_ascii=False)
    print(f"第{no}号「{meta['title']}」を組みました → docs/issues/{slug}.html")
    if dropped:
        print(f"⚠️ 実在確認できず落とした動画: {dropped}", file=sys.stderr)
    for w in warnings:
        print(f"⚠️ {w}", file=sys.stderr)


def write_cover(issues):
    """表紙（目次）。最新号を大きく、あとは3カラムずつ。扉と同じ黒地で連動させる。"""
    esc = lambda s: html.escape(str(s), quote=True)
    out = []
    for k, i in enumerate(issues):
        lead = k == 0
        span = 6 if lead else 3
        rest = len(issues) - 1
        if not lead and rest % 2 == 1 and k == len(issues) - 1:
            span = 6                      # 余った1枚は全幅にして穴を作らない
        img = i.get("hero")
        cls = "issue lead-issue" if lead else "issue"
        style = f"grid-column:span {span}"
        ghost = ""
        if img:
            style += f";background-image:url(img/{img})"
        else:
            cls += " glyph"
            ghost = f'<span class="ghost">{esc((i.get("glyph") or i["topic"])[:1])}</span>'
        body = [f'<span class="kicker">{esc(i["topic"])}</span>', f'<h2>{esc(i["title"])}</h2>']
        if lead:
            body.append(f'<p>{esc(card_lead(i["lead"]))}</p>')
        out.append(
            f'  <a class="{cls}" style="{style}" href="issues/{i["date"]}.html">\n'
            f'    {ghost}<span class="no">第 {i["no"]} 号　{esc(i["date_ja"])}</span>\n'
            f'    <span class="body">{"".join(body)}</span>\n  </a>')
    idx = open("templates/index.html", encoding="utf-8").read()
    open("docs/index.html", "w", encoding="utf-8").write(
        idx.replace("{{CARDS}}", "\n".join(out)).replace("{{COUNT}}", str(len(issues))))


if __name__ == "__main__":
    main()
