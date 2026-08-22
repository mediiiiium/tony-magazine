#!/usr/bin/env python3
"""扉の1枚を取ってくる（Met の Open Access → Wikimedia Commons の順）。

誌面の主役は冒頭の全面写真なので、毎号ここで1枚だけ確保する。
- META の hero_query（英語）でまず Met を検索し、パブリックドメインの作品だけ使う
- Met は美術品しか持っていないので、当たらなければ Commons に降りる
  （灯台・菌類・養蜂のような題材はこちらにしか無い）
- 収蔵品の記録写真は 4:3 のグレー背景で「図録」に見えるため、
  背景を多項式で近似して被写体を切り抜き、2400×1250 の扉に組み直す
- 絵画など画面全体が作品のものは、切り抜かずに寄せて切るだけにする

この工程はコケてもよい。失敗したら何も書かずに終わり、build_issue.py が
「題を一字置く扉」に切り替えて warnings に載せる（無言で落とさない）。
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

API = "https://collectionapi.metmuseum.org/public/collection/v1"
COMMONS = "https://commons.wikimedia.org/w/api.php"
# 二次利用できるライセンスだけ。表示義務は誌面のクレジットで果たす
OK_LICENSE = re.compile(r"(public domain|^pd|cc0|cc by(-sa)?)", re.I)
OUT_W, OUT_H = 2400, 1250
UA = {"User-Agent": "tony-magazine/1.0 (personal weekly zine)"}


def get(url, timeout=30, tries=4):
    """Met API は連続で叩くと 403 を返してくる。少し待って数回だけやり直す。"""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429, 500, 502, 503) or i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


def search(query, limit=25, **extra):
    p = {"q": query, "hasImages": "true", "isPublicDomain": "true"}
    p.update(extra)
    try:
        d = get(f"{API}/search?{urllib.parse.urlencode(p)}")
    except Exception as e:
        print(f"Met 検索に失敗: {e}", file=sys.stderr)
        return []
    return (d.get("objectIDs") or [])[:limit]


def relevant(o, words):
    """Met の全文検索は「どこかに語が出てくる」だけで拾うので、
       題名・分類・タグに語が入っているものだけ扉に使う（無関係な肖像画が来るのを防ぐ）。"""
    hay = " ".join(str(o.get(k) or "") for k in
                   ("title", "objectName", "classification", "culture", "medium", "department"))
    hay += " " + " ".join(t.get("term", "") for t in (o.get("tags") or []))
    hay = hay.lower()
    return any(w in hay for w in words)


def pick(ids, words):
    """使える1点を選ぶ。題材が合っていて、大きい原寸があり、極端に細長くないもの。"""
    for oid in ids:
        time.sleep(.25)                 # 続けて叩くと弾かれるので間を置く
        try:
            o = get(f"{API}/objects/{oid}")
        except Exception:
            continue
        url = o.get("primaryImage") or ""
        if not url or not o.get("isPublicDomain"):
            continue
        if words and not relevant(o, words):
            continue
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=90).read()
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            continue
        w, h = im.size
        if w < 1200 or h < 900:
            continue
        if not 0.55 <= h / w <= 1.6:      # 掛軸のような極端な縦長は扉に組めない
            continue
        return o, im
    return None, None


def flatness(im):
    """周縁が平坦なら「グレー背景の記録写真」。切り抜いてよいかの判定に使う。"""
    a = np.asarray(im.resize((320, 240), Image.LANCZOS)).astype(np.float32)
    b = 10
    edge = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3),
                           a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    return float(edge.std(axis=0).mean())


def cutout(im, paper, maxw=1700, keep_shadow=.45):
    """背景を2次多項式で近似し、残差で被写体のマスクを作る。
       単純な色距離だとグレーのグラデーション背景で白フチが出るのでこの方式。"""
    im = im.copy()
    im.thumbnail((maxw, maxw), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    h, w, _ = a.shape
    ys, xs = np.mgrid[0:h, 0:w]
    X, Y = xs / w - .5, ys / h - .5
    band = np.zeros((h, w), bool)
    b = max(6, int(min(h, w) * .035))
    band[:b, :] = band[-b:, :] = band[:, :b] = band[:, -b:] = True
    A = np.stack([np.ones_like(X), X, Y, X * X, X * Y, Y * Y], -1)
    fit = np.zeros_like(a)
    for c in range(3):
        coef, *_ = np.linalg.lstsq(A[band], a[..., c][band], rcond=None)
        fit[..., c] = A @ coef
    resid = np.linalg.norm(a - fit, axis=2)
    m = np.clip((resid - 14) / 34, 0, 1)
    darker = a.mean(2) < fit.mean(2) - 5          # 落ち影は薄く残すと浮かない
    m = np.where(darker & (m < keep_shadow),
                 np.maximum(m, np.clip((resid - 9) / 34, 0, 1) * keep_shadow), m)
    m[m < .06] = 0
    yy, xx = np.where(resid > 55)
    if len(yy) < 500:
        return None
    y0, y1, x0, x1 = yy.min(), yy.max(), xx.min(), xx.max()
    cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
    ry, rx = max(1, (y1 - y0) / 2), max(1, (x1 - x0) / 2)
    e = np.sqrt(((ys - cy) / (ry * 1.30)) ** 2 + ((xs - cx) / (rx * 1.30)) ** 2)
    m *= np.clip((1.0 - e) / 0.22, 0, 1)          # 切り抜きの四角い縁を消す
    m = np.asarray(Image.fromarray((m * 255).astype(np.uint8))
                   .filter(ImageFilter.GaussianBlur(1.4))) / 255.
    out = np.clip(a * m[..., None] + paper * (1 - m[..., None]), 0, 255).astype(np.uint8)
    Y0, Y1 = int(cy - ry * 1.36), int(cy + ry * 1.36)
    X0, X1 = int(cx - rx * 1.36), int(cx + rx * 1.36)
    W, H = X1 - X0, Y1 - Y0
    if W < 80 or H < 80:
        return None
    canvas = np.tile(np.asarray(paper, np.uint8), (H, W, 1))   # 足りない分は地色で継ぐ
    sy0, sx0 = max(0, Y0), max(0, X0)
    sy1, sx1 = min(h, Y1), min(w, X1)
    canvas[sy0 - Y0:sy1 - Y0, sx0 - X0:sx1 - X0] = out[sy0:sy1, sx0:sx1]
    alpha = np.zeros((H, W), np.float32)
    alpha[sy0 - Y0:sy1 - Y0, sx0 - X0:sx1 - X0] = m[sy0:sy1, sx0:sx1]
    return Image.fromarray(canvas), Image.fromarray((alpha * 255).astype(np.uint8))


def studio_hero(im):
    """記録写真 → 暗い地に被写体を1点置いた全面扉に組み直す。"""
    dark = np.array([26, 24, 22], np.float32)
    got = cutout(im, dark)
    if not got:
        return None
    obj, alpha = got
    bg = Image.new("RGB", (OUT_W, OUT_H), (26, 24, 22))
    # 背景に淡いスポットを置いて、平面的にならないようにする
    ys, xs = np.mgrid[0:OUT_H, 0:OUT_W]
    r = np.sqrt(((xs - OUT_W * .68) / (OUT_W * .55)) ** 2 + ((ys - OUT_H * .45) / (OUT_H * .8)) ** 2)
    glow = np.clip(1 - r, 0, 1)[..., None] * np.array([26, 23, 19], np.float32)
    bg = Image.fromarray((np.asarray(bg).astype(np.float32) + glow).clip(0, 255).astype(np.uint8))
    th = int(OUT_H * .84)
    tw = max(1, int(obj.width * th / obj.height))
    if tw > OUT_W * .5:
        tw = int(OUT_W * .5)
        th = max(1, int(obj.height * tw / obj.width))
    obj = obj.resize((tw, th), Image.LANCZOS)
    alpha = alpha.resize((tw, th), Image.LANCZOS)
    bg.paste(obj, (int(OUT_W * .60), (OUT_H - th) // 2), alpha)
    return bg


def crop_hero(im):
    """絵画など画面全体が作品のもの。寄せて切って、左に文字の乗る影を敷く。"""
    w, h = im.size
    scale = max(OUT_W / w, OUT_H / h)
    im = im.resize((int(w * scale + 1), int(h * scale + 1)), Image.LANCZOS)
    x = int((im.width - OUT_W) * .62)             # 少し右に寄せて左に余白を作る
    return im.crop((x, (im.height - OUT_H) // 2, x + OUT_W, (im.height - OUT_H) // 2 + OUT_H))


def commons_search(query, words, limit=30):
    """Commons のファイル名前空間を検索して、大きくてライセンスの明快なものを返す。"""
    p = {"action": "query", "format": "json", "generator": "search",
         "gsrnamespace": "6", "gsrsearch": f"{query} filetype:bitmap",
         "gsrlimit": str(limit), "prop": "imageinfo",
         "iiprop": "url|size|extmetadata", "iiurlwidth": "2400"}
    try:
        d = get(f"{COMMONS}?{urllib.parse.urlencode(p)}")
    except Exception as e:
        print(f"Commons 検索に失敗: {e}", file=sys.stderr)
        return []
    out = []
    for page in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        ex = ii.get("extmetadata", {}) or {}
        lic = (ex.get("LicenseShortName", {}) or {}).get("value", "")
        if not OK_LICENSE.search(lic):
            continue
        if ii.get("width", 0) < 2000:
            continue
        assessed = (ex.get("Assessments", {}) or {}).get("value", "").lower()
        name = page.get("title", "").replace("File:", "")
        # Commons の全文検索は説明文でも当たるので、ファイル名に語が入っているものだけ使う
        # （「養蜂」で道端のゴミ箱の写真が来るのを防ぐ）
        if words and not any(w in name.lower() for w in words):
            continue
        out.append({
            "title": name,
            "url": ii.get("thumburl") or ii.get("url"),
            "page": ii.get("descriptionurl", ""),
            "artist": re.sub(r"(?is)<[^>]+>", "", (ex.get("Artist", {}) or {}).get("value", "")).strip(),
            "license": lic,
            # 秀逸／良質画像は見栄えの当たりが大きいので優先する
            "rank": 2 if "featured" in assessed else 1 if "quality" in assessed else 0,
            "width": ii.get("width", 0),
        })
    out.sort(key=lambda x: (-x["rank"], -x["width"]))
    return out


def commons_pick(query, words):
    for c in commons_search(query, words):
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(c["url"], headers=UA), timeout=90).read()
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            continue
        w, h = im.size
        if w < 1600 or h / w > 1.1:      # 扉は横長。縦位置の写真は組めない
            continue
        return c, im
    return None, None


def commons_credit(c):
    bits = [b for b in (c["title"].rsplit(".", 1)[0], c["artist"]) if b]
    return (f'{", ".join(bits)}<br>Wikimedia Commons（{html_escape(c["license"])}）'
            f' <a href="{c["page"]}">この写真のページ</a>')


def html_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def credit_html(o):
    bits = [b for b in (o.get("title"), o.get("artistDisplayName"), o.get("objectDate")) if b]
    line1 = ", ".join(bits)
    return (f"{line1}<br>The Metropolitan Museum of Art, Open Access "
            f'<a href="{o.get("objectURL", "")}">#{o.get("objectID")}</a>')


def main():
    slug = os.environ.get("DATE_SLUG")
    if not slug:
        print("DATE_SLUG が未設定", file=sys.stderr)
        return 1
    if not os.path.exists("issue_raw.txt"):
        print("原稿がないので扉の写真は取りません", file=sys.stderr)
        return 0
    raw = open("issue_raw.txt", encoding="utf-8").read()
    m = re.search(r"(?s)<!--META\s*(\{.*?\})\s*META-->", raw)
    if not m:
        print("META が読めないので扉の写真は取りません", file=sys.stderr)
        return 0
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError:
        return 0
    query = (meta.get("hero_query") or "").strip()
    if not query:
        print("hero_query が無いので扉の写真は取りません", file=sys.stderr)
        return 0

    words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 3]
    # 題名で当たるのがいちばん確実。外したらタグ、最後に全文検索＋題材フィルタ
    o = im = None
    for ids, filt in ((search(query, title="true"), words),
                      (search(query, tags="true"), words),
                      (search(query), words),
                      (search(query.split()[0]) if " " in query else [], words)):
        if not ids:
            continue
        o, im = pick(ids, filt)
        if im is not None:
            break
    if im is not None:
        # 収蔵品の記録写真は切り抜いて組み直す。絵画などは寄せて切るだけ
        hero = studio_hero(im) if flatness(im) < 12 else None
        if hero is None:
            hero = crop_hero(im)
        side = {"credit_html": credit_html(o), "alt": o.get("title", ""),
                "source": "met", "object_id": o.get("objectID"), "query": query}
        label = f"Met #{o.get('objectID')} {o.get('title')}"
    else:
        print(f"Met に使える図版が無いので Commons を見ます: {query}", file=sys.stderr)
        c, cim = commons_pick(query, words)
        if cim is None:
            print(f"扉の図版が見つかりませんでした: {query}", file=sys.stderr)
            return 0
        hero = crop_hero(cim)
        side = {"credit_html": commons_credit(c), "alt": c["title"],
                "source": "commons", "page": c["page"], "query": query}
        label = f"Commons {c['title']}"

    os.makedirs("docs/img", exist_ok=True)
    hero.save(f"docs/img/{slug}.webp", "WEBP", quality=82, method=6)
    json.dump(side, open(f"docs/img/{slug}.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"扉の図版: {label} → docs/img/{slug}.webp", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
