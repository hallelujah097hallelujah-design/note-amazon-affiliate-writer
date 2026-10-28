#!/usr/bin/env python3
"""Fetch one pinned rule snapshot from public GitHub without credentials."""
import argparse
import concurrent.futures
import json
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "hallelujah097hallelujah-design/note-amazon-affiliate-writer"
BRANCH = "main"
LOADER_VERSION = "2.0.0"
MAX_BYTES = 2 * 1024 * 1024
REQUIRED = (
    "SKILL.md",
    "references/01_収益化戦略・KW・SERP・商品調査.md",
    "references/02_記事構成・本文・Amazon導線.md",
    "references/03_品質採点・ファクトチェック.md",
    "references/04_公開・運用・30記事検証.md",
    "references/05_納品フォーマット・停止条件.md",
)


class FetchError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FetchError("取得先が変更されています。管理者に確認してください。")


def read_url(url):
    parsed = urlsplit(url)
    allowed = (
        parsed.hostname == "api.github.com"
        and parsed.path == f"/repos/{REPOSITORY}/commits/{BRANCH}"
    ) or (
        parsed.hostname == "raw.githubusercontent.com"
        and parsed.path.startswith(f"/{REPOSITORY}/")
    )
    if parsed.scheme != "https" or parsed.port not in (None, 443) or not allowed:
        raise FetchError("許可された配布元以外のURLです。")
    if parsed.username or parsed.password:
        raise FetchError("認証情報を含むURLは使用できません。")
    # urllib does not read netrc or GitHub CLI credentials. No Authorization header.
    request = Request(url, headers={
        "Accept": "application/vnd.github+json" if parsed.hostname == "api.github.com" else "text/plain",
        "Cache-Control": "no-cache, no-store",
        "User-Agent": "note-amazon-affiliate-writer/" + LOADER_VERSION,
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200:
                raise FetchError("配布元から正常な応答がありません。")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError("配布データがサイズ上限を超えています。")
            return data
    except HTTPError as error:
        if error.code == 404:
            raise FetchError("公開ルールを取得できません（404）。公開設定とファイルを確認してください。") from error
        if error.code in (403, 429):
            raise FetchError("GitHubの取得制限またはアクセス制限です。時間を置いて再実行してください。") from error
        raise FetchError(f"配布元のHTTPエラーです（{error.code}）。") from error


def decode_text(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise FetchError("配布データの形式またはサイズが不正です。")
    text = data.decode("utf-8")
    if not text.strip() or "\x00" in text or re.search(r"<!doctype\s+html|<html(?:\s|>)", text[:300], re.I):
        raise FetchError("ルールではない空データまたはHTMLが返されました。")
    return text


def fetch_rules(output_parent, transport=read_url):
    # The CLI has no URL/ref override; injected transports are for isolated tests.
    head_url = f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}?request={uuid.uuid4().hex}"
    head = json.loads(decode_text(transport(head_url)))
    revision = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise FetchError("mainの版を確認できません。")

    def fetch_one(path):
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{quote(path, safe='/')}"
        return path, decode_text(transport(url))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        files = dict(executor.map(fetch_one, REQUIRED))
    if not files["SKILL.md"].startswith("---\n"):
        raise FetchError("SKILL.mdの書式が不正です。")
    frontmatter = files["SKILL.md"].split("---", 2)[1]
    if not re.search(r"^name:\s*note-amazon-affiliate-writer\s*$", frontmatter, re.M):
        raise FetchError("異なるスキルのルールです。")
    match = re.search(r'^\s*version:\s*[\"\']?([0-9]+\.[0-9]+\.[0-9]+)[\"\']?\s*$', frontmatter, re.M)
    if not match:
        raise FetchError("制作ルールの版を確認できません。")
    for path in REQUIRED[1:]:
        if not files[path].lstrip().startswith("# "):
            raise FetchError("参照資料の書式が不正です：" + path)
    # Publish nothing until all six files have passed validation.
    parent = Path(output_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="note-amazon-rules-", dir=parent))
    try:
        for path, content in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        result = {
            "ok": True, "version": match.group(1), "revision": revision,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "repository": REPOSITORY, "branch": BRANCH,
            "snapshot_dir": str(root), "file_count": len(files),
            "loader_version": LOADER_VERSION, "authentication": "none",
        }
        (root / "receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    except Exception:
        shutil.rmtree(root)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-parent", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(fetch_rules(args.output_parent), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error), "action": "最新版を取得できないため制作を停止してください。旧版で続行しないでください。"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
