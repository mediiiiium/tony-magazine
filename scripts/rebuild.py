#!/usr/bin/env python3
"""保管してある生原稿から過去号を組み直す。

誌面のデザイン（templates/ や style.css、build_issue.py の組版）を変えたとき、
過去号は古いHTMLのまま取り残される。これを走らせると archive/ の生原稿を
いまの組版で組み直し、表紙も作り直す。

    python scripts/rebuild.py              # 台帳にある全号
    python scripts/rebuild.py 2026-08-23   # 号を指定

生原稿が無い号（保管を始める前に出した号）は飛ばして最後に知らせる。
"""
import json
import os
import subprocess
import sys

ARCHIVE_DIR = "archive"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    os.chdir(ROOT)
    issues = json.load(open("docs/issues.json", encoding="utf-8"))
    want = sys.argv[1:]
    targets = [i for i in issues if not want or i["date"] in want]
    if want:
        for w in want:
            if not any(i["date"] == w for i in targets):
                sys.exit(f"{w} は台帳にありません")

    done, skipped, failed = [], [], []
    for i in sorted(targets, key=lambda x: x["date"]):   # 古い号から順に
        slug = i["date"]
        if not os.path.exists(f"{ARCHIVE_DIR}/{slug}.txt"):
            skipped.append(f'第{i["no"]}号 {slug}')
            continue
        env = dict(os.environ, DATE_SLUG=slug, DATE_JA=i["date_ja"], REBUILD="1")
        r = subprocess.run([sys.executable, "scripts/build_issue.py"], env=env)
        (done if r.returncode == 0 else failed).append(f'第{i["no"]}号 {slug}')

    print()
    print(f"組み直した: {len(done)}号 " + (" / ".join(done) if done else ""))
    if skipped:
        print(f"生原稿が無く飛ばした: " + " / ".join(skipped))
    if failed:
        print(f"⚠️ 失敗: " + " / ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
