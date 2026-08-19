#!/usr/bin/env python3
"""editorial.md + 過去号一覧 + 今号の情報 から claude -p に渡す prompt.txt を組み立てる。"""
import json
import os

editorial = open("prompts/editorial.md", encoding="utf-8").read()
issues = json.load(open("docs/issues.json", encoding="utf-8"))

past = "\n".join(f"- 第{i['no']}号（{i['date']}）: {i['topic']} —「{i['title']}」" for i in issues) \
       or "- まだ過去号はありません（この号が実質の初回です）"

issue_no = len(issues) + 1
date_ja = os.environ.get("DATE_JA", "")

prompt = f"""{editorial}

# 過去号（これらと近接領域は避ける）
{past}

# 今号
第{issue_no}号 / 発行日 {date_ja}
それでは、今号のテーマを選んで執筆してください。
"""
open("prompt.txt", "w", encoding="utf-8").write(prompt)
print(f"prompt.txt: {len(prompt)}文字 / 第{issue_no}号")
