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

それでは、今号のテーマを選んで執筆してください。
"""
open("prompt.txt", "w", encoding="utf-8").write(prompt)
print(f"prompt.txt: {len(prompt)}文字 / 第{issue_no}号")
