#!/usr/bin/env python3
"""連載「今週の若手」の1人を、データで選ぶ。

ESPN の公開 JSON（site.api.espn.com。非公式だが鍵なしで読める）から、
欧州7リーグ＋J1 の全クラブの名簿と、今季の全試合の出場記録を集め、23歳以下を点数にする。
考え方は既存の若手評価サービス（CIES など）と同じで、出場時間（監督の信頼）を重く見て、
90分あたりの成績・リーグの強さ・若さで補正する。ポジションで物差しを変える:

  攻撃(F) / 中盤(M): 信頼 40% ・ ゴール＋アシスト/90 45% ・ シュート/90 15%
  守備(D):           信頼 40% ・ 守りの結果 35%（出ている間の失点/90、フル出場の無失点）
                     ・ ゴール＋アシスト/90 15% ・ 規律 10%
  守備(G):           信頼 35% ・ セーブ率 35% ・ 無失点の割合 20% ・ セーブ/90 10%

各項目は同じポジションの全リーグ横断の順位（0〜1）にしてから重みをかける。
DF の「出ている間の失点」はチームの守備の成績と混ざる（選手ごとのタックル等は ESPN に無い）。

1号に1人。ポジションは週ごとに 攻撃 → 中盤 → 守備 と回し、月の最初の号は日本人かJリーグの選手。
同じ枠の上位から、今週の試合で出来事（ゴール・アシスト・無失点・デビュー）がある選手を優先する。
一度出た選手は1年出さない（docs/rookies.json）。

出力: pick.json（選んだ1人のデータ。make_prompt.py と build_issue.py が読む）
試合の抽出結果は data/scout/<league>.json に貯め、次の週は新しい試合だけ取りに行く。
"""
import concurrent.futures
import datetime
import json
import os
import re
import sys
import time
import urllib.request

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
# リーグ: (誌面の名前, 強さの補正)。強さは UEFA の国別係数のおおよその序列に合わせた手づけ
LEAGUES = {
    "eng.1": ("プレミアリーグ", 1.00),
    "esp.1": ("ラ・リーガ", 0.95),
    "ger.1": ("ブンデスリーガ", 0.90),
    "ita.1": ("セリエA", 0.90),
    "fra.1": ("リーグ・アン", 0.85),
    "por.1": ("リーガ・ポルトガル", 0.75),
    "ned.1": ("エールディヴィジ", 0.72),
    "jpn.1": ("J1リーグ", 0.62),
}
MAX_AGE = 23
MIN_MINUTES = 360        # これ未満の出場時間の選手は点数にしない（数試合の当たり外れを避ける）
MIN_SHOTS_FACED = 15     # GK のセーブ率はこれ未満だとぶれるので対象外
AGE_BONUS = 0.04         # 23歳から1歳若いごとに +4%
EVENT_BONUS = 1.15       # 今週の出来事がある選手の点数をこれだけ上げて選ぶ
TOP_N = 10               # 出来事を探すのは枠の上位この人数まで
COOLDOWN_DAYS = 365
ROTATION = ["攻撃", "中盤", "守備"]
GROUP_OF = {"F": "攻撃", "M": "中盤", "D": "守備", "G": "守備"}
CACHE_DIR = "data/scout"
WORKERS = 8


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tony-magazine/1.0"})
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def minute(clock):
    """"45'+6'" → 45, "90'+3'" → 90, "62'" → 62。読めなければ None。"""
    m = re.match(r"\s*(\d+)", clock or "")
    return int(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────
# 収集
# ─────────────────────────────────────────────────────────────
def extract_match(lg, eid):
    """試合の要約から、点数づけに要る分だけを抜き出す。"""
    d = get(f"{BASE}{lg}/summary?event={eid}")
    comp = d["header"]["competitions"][0]
    if not comp["status"]["type"].get("completed"):
        return None
    goals = []
    for k in d.get("keyEvents", []):
        if k.get("scoringPlay") and k.get("team"):
            goals.append({"team": k["team"]["id"], "min": minute(k["clock"]["displayValue"]) or 0})
    players = []
    for side in d.get("rosters", []):
        tid = side["team"]["id"]
        for p in side.get("roster", []):
            st = {s["name"]: s.get("value") or 0 for s in p.get("stats", [])}
            subs = [minute(x["clock"]["displayValue"]) for x in p.get("plays", []) if x.get("substitution")]
            reds = [minute(x["clock"]["displayValue"]) for x in p.get("plays", []) if x.get("redCard")]
            starter, sub_in, sub_out = bool(p.get("starter")), bool(p.get("subbedIn")), bool(p.get("subbedOut"))
            if not starter and not sub_in:
                continue
            start = 0 if starter else (subs[0] if subs else 90)
            end = 90
            if sub_out and subs:
                end = subs[-1]
            if reds and reds[0] is not None:
                end = min(end, reds[0])
            players.append({"id": p["athlete"]["id"], "team": tid, "starter": starter,
                            "start": start or 0, "end": max(end or 0, start or 0),
                            "g": st.get("totalGoals", 0), "a": st.get("goalAssists", 0),
                            "sh": st.get("totalShots", 0), "sv": st.get("saves", 0),
                            "yc": st.get("yellowCards", 0), "rc": st.get("redCards", 0)})
    return {"id": eid, "date": comp["date"][:10],
            "teams": [c["team"]["id"] for c in comp["competitors"]],
            "goals": goals, "players": players}


def collect():
    """名簿（23歳以下）と今季の全試合を集める。試合は data/scout/ に貯めて差分だけ取る。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    roster, teams, matches = {}, {}, {}
    for lg in LEAGUES:
        path = f"{CACHE_DIR}/{lg}.json"
        cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        todo = set()
        for t in get(f"{BASE}{lg}/teams")["sports"][0]["leagues"][0]["teams"]:
            tm = t["team"]
            logo = (tm.get("logos") or [{}])[0].get("href", "")
            teams[tm["id"]] = {"name": tm["displayName"], "lg": lg, "logo": logo}
            for a in get(f"{BASE}{lg}/teams/{tm['id']}/roster").get("athletes", []):
                if (a.get("age") or 99) > MAX_AGE:
                    continue
                roster[a["id"]] = {"id": a["id"], "name": a["displayName"], "age": a["age"],
                                   "born": (a.get("dateOfBirth") or "")[:10],
                                   "pos": (a.get("position") or {}).get("abbreviation", ""),
                                   "nat": a.get("citizenship", ""), "team": tm["id"], "lg": lg}
            for e in get(f"{BASE}{lg}/teams/{tm['id']}/schedule").get("events", []):
                if e["competitions"][0]["status"]["type"].get("completed") and e["id"] not in cache:
                    todo.add(e["id"])
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
            for eid, m in zip(todo, ex.map(lambda i: extract_match(lg, i), todo)):
                if m:
                    cache[eid] = m
        json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        matches[lg] = cache
        print(f"{lg}: 試合 {len(cache)}（新規 {len(todo)}）", file=sys.stderr)
    return roster, teams, matches


# ─────────────────────────────────────────────────────────────
# 集計と点数
# ─────────────────────────────────────────────────────────────
def season_start(pub):
    """今季の始まり。欧州も J1（2026-27 から秋春制）も7月1日で区切る。"""
    return datetime.date(pub.year if pub.month >= 7 else pub.year - 1, 7, 1)


def aggregate(roster, teams, matches, pub):
    week_from = pub - datetime.timedelta(days=7)
    since = season_start(pub).isoformat()
    team_games = {}
    for lg, cache in matches.items():
        for m in cache.values():
            if not since <= m["date"] <= pub.isoformat():
                continue
            for tid in m["teams"]:
                team_games.setdefault(tid, []).append(m)
    for ms in team_games.values():
        ms.sort(key=lambda m: m["date"])

    out = []
    for pid, r in roster.items():
        games = team_games.get(r["team"], [])
        if not games:
            continue
        s = dict(apps=0, starts=0, mins=0, full=0, g=0, a=0, sh=0, sv=0, ga_on=0, cs_full=0, yc=0, rc=0)
        log = []        # チームの全試合について、その選手の出場時間（出ていなければ 0）
        events = []
        first = None
        for m in games:
            p = next((x for x in m["players"] if x["id"] == pid and x["team"] == r["team"]), None)
            if not p:
                log.append({"date": m["date"], "mins": 0})
                continue
            mins = max(0, p["end"] - p["start"])
            ga = sum(1 for g in m["goals"] if g["team"] != r["team"]
                     and p["start"] <= g["min"] and (g["min"] < p["end"] or p["end"] == 90))
            s["apps"] += 1
            s["starts"] += p["starter"]
            s["mins"] += mins
            s["full"] += mins >= 90
            s["cs_full"] += mins >= 90 and ga == 0
            s["ga_on"] += ga
            for k in ("g", "a", "sh", "sv", "yc", "rc"):
                s[k] += p[k]
            log.append({"date": m["date"], "mins": mins, "g": p["g"], "a": p["a"]})
            first = first or m["date"]
            if datetime.date.fromisoformat(m["date"]) > week_from:
                ev = []
                if p["g"]:
                    ev.append(f"{int(p['g'])}ゴール")
                if p["a"]:
                    ev.append(f"{int(p['a'])}アシスト")
                if mins >= 90 and ga == 0 and r["pos"] in ("D", "G"):
                    ev.append("フル出場で無失点")
                if r["pos"] == "G" and p["sv"] >= 5:
                    ev.append(f"{int(p['sv'])}セーブ")
                if first == m["date"]:
                    ev.append("今季初出場")
                if ev:
                    opp = next((t for t in m["teams"] if t != r["team"]), "")
                    events.append({"date": m["date"], "vs": teams.get(opp, {}).get("name", ""), "what": ev})
        if s["mins"] < MIN_MINUTES:
            continue
        per90 = lambda v: v * 90 / s["mins"]
        row = dict(r, **s, group=GROUP_OF.get(r["pos"], ""), team_games=len(games),
                   team_name=teams[r["team"]]["name"], logo=teams[r["team"]]["logo"],
                   league=LEAGUES[r["lg"]][0],
                   start_share=s["starts"] / len(games), ga90=per90(s["ga_on"]),
                   ga_a90=per90(s["g"] + s["a"]), sh90=per90(s["sh"]),
                   cards90=per90(s["yc"] + 3 * s["rc"]), sv90=per90(s["sv"]),
                   faced=s["sv"] + s["ga_on"],
                   save_pct=s["sv"] / (s["sv"] + s["ga_on"]) if s["sv"] + s["ga_on"] else 0,
                   cs_rate=s["cs_full"] / max(s["apps"], 1),
                   last5=log[-5:], events=events)
        if row["group"]:
            out.append(row)
    return out


def pct(rows, key, reverse=False):
    """rows の key を、同じ集団の中の順位（0〜1、1が最良）にして row['p_'+key] に入れる。"""
    vals = sorted(r[key] for r in rows)
    n = len(vals)
    for r in rows:
        below = sum(1 for v in vals if v < r[key])
        p = below / (n - 1) if n > 1 else 1.0
        r["p_" + key] = 1 - p if reverse else p


def score(rows):
    for grp in ("攻撃", "中盤"):
        rs = [r for r in rows if r["group"] == grp]
        for k in ("start_share", "ga_a90", "sh90"):
            pct(rs, k)
        for r in rs:
            r["parts"] = {"信頼": .40 * r["p_start_share"], "ゴール＋アシスト": .45 * r["p_ga_a90"],
                          "シュート": .15 * r["p_sh90"]}
    ds = [r for r in rows if r["pos"] == "D"]
    for k in ("start_share", "ga_a90", "cs_rate"):
        pct(ds, k)
    pct(ds, "ga90", reverse=True)
    pct(ds, "cards90", reverse=True)
    for r in ds:
        r["parts"] = {"信頼": .40 * r["p_start_share"],
                      "守りの結果": .25 * r["p_ga90"] + .10 * r["p_cs_rate"],
                      "ゴール＋アシスト": .15 * r["p_ga_a90"], "規律": .10 * r["p_cards90"]}
    gs = [r for r in rows if r["pos"] == "G" and r["faced"] >= MIN_SHOTS_FACED]
    for k in ("start_share", "save_pct", "cs_rate", "sv90"):
        pct(gs, k)
    for r in gs:
        r["parts"] = {"信頼": .35 * r["p_start_share"], "セーブ率": .35 * r["p_save_pct"],
                      "無失点": .20 * r["p_cs_rate"], "忙しさ": .10 * r["p_sv90"]}
    scored = [r for r in rows if "parts" in r]
    for r in scored:
        base = sum(r["parts"].values())
        r["score"] = base * LEAGUES[r["lg"]][1] * (1 + AGE_BONUS * max(0, MAX_AGE - r["age"]))
    return scored


def league_ranks(rows, r):
    """誌面のグラフ用: 同じリーグ・同じ枠の23歳以下の中での順位。"""
    peers = [x for x in rows if x["lg"] == r["lg"] and x["group"] == r["group"]]
    rank = lambda key, rev=True: 1 + sum(1 for x in peers if (x[key] > r[key] if rev else x[key] < r[key]))
    ranks = {"peers": len(peers), "mins": rank("mins"), "score": rank("score")}
    if r["pos"] == "G":
        ranks.update(save_pct=rank("save_pct"), cs_full=rank("cs_full"))
    elif r["pos"] == "D":
        ranks.update(ga90=rank("ga90", rev=False), cs_full=rank("cs_full"), ga_a90=rank("ga_a90"))
    else:
        ranks.update(g=rank("g"), a=rank("a"), ga_a90=rank("ga_a90"))
    return ranks


def choose(rows, pub, featured):
    week = pub.isocalendar()[1]
    group = ROTATION[week % len(ROTATION)]
    japan = pub.day <= 7          # 月の最初の号
    recent = {name for name, d in featured.items()
              if (pub - datetime.date.fromisoformat(d)).days < COOLDOWN_DAYS}
    pool = [r for r in rows if r["name"] not in recent]
    is_jp = lambda r: r["nat"] == "Japan" or r["lg"] == "jpn.1"
    cands = [r for r in pool if r["group"] == group and (is_jp(r) or not japan)]
    if japan and not cands:
        cands = [r for r in pool if is_jp(r)]     # その枠に日本人がいなければ枠を外す
    cands.sort(key=lambda r: -r["score"])
    top = cands[:TOP_N]
    if not top:
        return None, group, japan
    pick = max(top, key=lambda r: r["score"] * (EVENT_BONUS if r["events"] else 1))
    return pick, group, japan


def main():
    slug = os.environ.get("DATE_SLUG") or datetime.date.today().isoformat()
    pub = datetime.date.fromisoformat(slug)
    featured = {}
    if os.path.exists("docs/rookies.json"):
        for r in json.load(open("docs/rookies.json", encoding="utf-8")):
            for n in r.get("ids", r.get("names", [])):
                featured.setdefault(n, r["date"])
    roster, teams, matches = collect()
    rows = score(aggregate(roster, teams, matches, pub))
    pick, group, japan = choose(rows, pub, featured)
    if not pick:
        json.dump({"ok": False, "reason": f"{group}の候補がいません"}, open("pick.json", "w"), ensure_ascii=False)
        print("候補なし", file=sys.stderr)
        return 1
    pick["ranks"] = league_ranks(rows, pick)
    keep = ("id", "name", "age", "born", "pos", "nat", "lg", "league", "team_name", "logo", "group",
            "apps", "starts", "mins", "full", "g", "a", "sh", "sv", "ga_on", "cs_full", "team_games",
            "start_share", "ga90", "ga_a90", "save_pct", "score", "parts", "last5", "events", "ranks")
    out = {"ok": True, "slot": group, "japan_week": japan, "pool": len(rows),
           **{k: pick[k] for k in keep},
           "p": {k[2:]: v for k, v in pick.items() if k.startswith("p_")}}
    others = sorted([r for r in rows if r["group"] == group], key=lambda r: -r["score"])[:5]
    out["runners_up"] = [f'{r["name"]}（{r["team_name"]}・{r["score"]:.2f}）' for r in others if r is not pick]
    json.dump(out, open("pick.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"今週の若手（{group}{'・日本人週' if japan else ''}）: {pick['name']} / {pick['team_name']} "
          f"/ {pick['age']}歳 / 点 {pick['score']:.2f} / 候補 {len(rows)}人", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
