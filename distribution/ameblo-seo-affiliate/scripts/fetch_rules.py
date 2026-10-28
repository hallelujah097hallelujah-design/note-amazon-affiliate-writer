#!/usr/bin/env python3
"""Fetch a pinned snapshot of public Ameblo rules without credentials."""
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

REPOSITORY = 'hallelujah097hallelujah-design/note-amazon-affiliate-writer'
BRANCH = 'main'
PREFIX = 'ameblo'
NAME = 'ameblo-seo-affiliate'
LOADER_VERSION = '1.0.0'
MAX_BYTES = 2 * 1024 * 1024
MAX_TOTAL = 10 * 1024 * 1024
REQUIRED = {
    'SKILL.md', 'references/01-research.md', 'references/02-ameblo-html.md',
    'references/03-structure.md', 'references/04-scoring.md',
    'references/05-writing.md', 'references/06-delivery.md',
    'references/07-monetization.md', 'references/08-optimization.md',
    'references/09-tools.md',
}


class FetchError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise FetchError('取得先が変更されています。管理者に確認してください。')


def read_url(url):
    parsed = urlsplit(url)
    allowed = (
        parsed.hostname == 'api.github.com'
        and parsed.path == f'/repos/{REPOSITORY}/commits/{BRANCH}'
    ) or (
        parsed.hostname == 'raw.githubusercontent.com'
        and re.fullmatch(
            '/' + re.escape(REPOSITORY) + r'/[a-f0-9]{40}/' + PREFIX + r'/.+',
            parsed.path,
        ) is not None
    )
    if (parsed.scheme != 'https' or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment or not allowed):
        raise FetchError('許可された公開配布元以外のURLです。')
    request = Request(url, headers={
        'Accept': 'application/vnd.github+json' if parsed.hostname == 'api.github.com' else 'text/plain',
        'Cache-Control': 'no-cache, no-store',
        'User-Agent': NAME + '/' + LOADER_VERSION,
    })
    # No Authorization header, netrc, GitHub CLI, or connector credentials.
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            if response.status != 200:
                raise FetchError('配布元から正常な応答がありません。')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError('配布データがサイズ上限を超えています。')
            return data
    except HTTPError as error:
        if error.code == 404:
            raise FetchError('公開ルールを取得できません（404）。公開設定とファイルを確認してください。') from error
        if error.code in (403, 429):
            raise FetchError('GitHubの取得制限またはアクセス制限です。時間を置いて再実行してください。') from error
        raise FetchError(f'配布元のHTTPエラーです（{error.code}）。') from error


def decode_text(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise FetchError('配布データの形式またはサイズが不正です。')
    text = data.decode('utf-8')
    if (not text.strip() or '\x00' in text
            or re.search(r'<!doctype\s+html|<html(?:\s|>)', text[:300], re.I)):
        raise FetchError('ルールではない空データまたはHTMLが返されました。')
    return text


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or manifest.get('name') != NAME:
        raise FetchError('マニフェストの形式または対象スキルが不正です。')
    version = manifest.get('version')
    files = manifest.get('files')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise FetchError('制作ルールの版を確認できません。')
    if not isinstance(files, list) or not 10 <= len(files) <= 50:
        raise FetchError('資料一覧が不正です。')
    for path in files:
        if not isinstance(path, str) or not re.fullmatch(r'SKILL\.md|references/[A-Za-z0-9_-]+\.md', path):
            raise FetchError('許可されていない資料パスです。')
    if len(set(files)) != len(files) or not REQUIRED.issubset(files):
        raise FetchError('必須資料が不足しているか資料が重複しています。')
    return version, files


def fetch_rules(output_parent, transport=read_url):
    # One resolved SHA pins the manifest and every document, even if main moves.
    url = f'https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}?request={uuid.uuid4().hex}'
    head = json.loads(decode_text(transport(url)))
    revision = head.get('sha') if isinstance(head, dict) else None
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise FetchError('mainの版を確認できません。')
    base = f'https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{PREFIX}/'
    manifest_text = decode_text(transport(base + 'rules-manifest.json'))
    version, paths = validate_manifest(json.loads(manifest_text))

    def fetch_one(path):
        return path, decode_text(transport(base + quote(path, safe='/')))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        files = dict(executor.map(fetch_one, paths))
    if sum(len(text.encode('utf-8')) for text in files.values()) > MAX_TOTAL:
        raise FetchError('資料全体がサイズ上限を超えています。')
    skill = files['SKILL.md']
    if not skill.startswith('---\n') or len(skill.split('---', 2)) != 3:
        raise FetchError('SKILL.mdの書式が不正です。')
    if not re.search(r'^name:\s*' + NAME + r'\s*$', skill.split('---', 2)[1], re.M):
        raise FetchError('異なるスキルのルールです。')
    for path, text in files.items():
        if path != 'SKILL.md' and not text.lstrip().startswith('# '):
            raise FetchError('参照資料の書式が不正です：' + path)
    # Create the snapshot only after all downloads and checks succeed.
    parent = Path(output_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='ameblo-rules-', dir=parent))
    try:
        for path, text in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        (root / 'rules-manifest.json').write_text(manifest_text, encoding='utf-8')
        result = {
            'ok': True, 'version': version, 'revision': revision,
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'repository': REPOSITORY, 'branch': BRANCH, 'rules_path': PREFIX,
            'snapshot_dir': str(root), 'file_count': len(files),
            'loader_version': LOADER_VERSION, 'authentication': 'none',
        }
        (root / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return result
    except Exception:
        shutil.rmtree(root)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-parent', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(fetch_rules(args.output_parent), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error), 'action': '最新版を取得できないため制作を停止してください。旧版で続行しないでください。'}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
