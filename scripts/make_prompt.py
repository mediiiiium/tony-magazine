#!/usr/bin/env python3
"""editorial.md + 過去号一覧 + 今号の情報 から claude -p に渡す prompt.txt を組み立てる。"""
import datetime
import json
import os

WEEK_DAYS = 7   # 「今週のトピックス」が拾ってよい期間（発行日から遡る日数）

editorial = open("prompts/editorial.md", encoding="utf-8").read()
issues = json.load(open("docs/issues.json", encoding="utf-8"))

past = "\n".join(f"- 第{i['no']}号（{i['date']}）: {i['topic']} —「{i['title']}」" for i in issues) \
       or "- まだ過去号はありません（この号が実質の初回です）"

# 今週の若手（scout.py がデータで選んだ1人）。選べなかった週は欄ごと書かせない
POS_JA = {"F": "FW", "M": "MF", "D": "DF", "G": "GK"}
try:
    pick = json.load(open("pick.json", encoding="utf-8"))
except FileNotFoundError:
    pick = {"ok": False}
if pick.get("ok"):
    events = "\n".join(f"  - {e['date']} vs {e['vs']}: {'・'.join(e['what'])}" for e in pick["events"]) \
             or "  - （今週の試合での目立った記録はなし。今季の積み上げで選ばれた）"
    rookie = f"""選手: {pick['name']}（ESPN 表記）
所属: {pick['team_name']}（{pick['league']}）／ {pick['age']}歳（{pick['born']}生）／ {POS_JA.get(pick['pos'], pick['pos'])} ／ 国籍 {pick['nat']}
今季: {pick['team_games']}試合中 先発{pick['starts']}・出場{pick['apps']}・{pick['mins']}分・{int(pick['g'])}ゴール・{int(pick['a'])}アシスト
選ばれた枠: {pick['slot']}（同じ枠・23歳以下・7リーグ＋J1 の{pick['pool']}人から点数で選出）
今週の記録:
{events}"""
else:
    rookie = "今週は選手を選べなかった。<section class=\"rookies\"> は書かない"

issue_no = len(issues) + 1
date_ja = os.environ.get("DATE_JA", "")

# 「今週」を日付で明示する。LLM に今日が何日かを察させない（速報性はここが要）
slug = os.environ.get("DATE_SLUG") or ""
try:
    pub = datetime.date.fromisoformat(slug)
except ValueError:
    pub = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    slug = pub.isoformat()
since = pub - datetime.timedelta(days=WEEK_DAYS - 1)

prompt = f"""{editorial}

# 過去号（これらと近接領域は避ける）
{past}

# 今号
第{issue_no}号 / 発行日 {date_ja}（{slug}）

**今週 = {since} 〜 {slug}**
「今週のトピックス」に入れてよいのは、この期間に報じられた／起きたことだけ。
各 <li> の data-date はこの範囲に収まるはずで、外れた項目は誌面に載る前に落とされる。
（特集はこの期間に縛られない。古い題材でよい）

# 今週の若手（この選手について書く）
{rookie}

それでは、今号のテーマを選んで執筆してください。
"""
open("prompt.txt", "w", encoding="utf-8").write(prompt)
print(f"prompt.txt: {len(prompt)}文字 / 第{issue_no}号")
