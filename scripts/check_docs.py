"""Check public Markdown file links and Python examples without launching SC2.

Run from any working directory: python scripts/check_docs.py
External URLs and heading fragments are not fetched or validated.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r'^```([^\n]*)\n(.*?)^```\s*$', re.MULTILINE | re.DOTALL)
LINK = re.compile(r'\[[^\]\n]+\]\(([^)\n]+)\)')
RAW = Path('evidence/2026-10-28/four-client-success')


def main() -> int:
    paths = set(ROOT.glob('*.md'))
    for folder in ('docs', 'examples', 'maps', '.github'):
        paths.update((ROOT / folder).rglob('*.md'))
    paths.update((ROOT / 'evidence').glob('*.md'))
    paths.update((ROOT / 'evidence').glob('*/*.md'))
    errors = []
    links = snippets = 0
    for path in sorted(paths):
        content = path.read_text(encoding='utf-8')
        for fence in FENCE.finditer(content):
            if fence.group(1).strip() in ('python', 'py'):
                snippets += 1
                try:
                    ast.parse(fence.group(2), filename=str(path.relative_to(ROOT)))
                except SyntaxError as exc:
                    errors.append(f'{path.relative_to(ROOT)}: invalid Python example: {exc.msg}')
        for match in LINK.finditer(FENCE.sub('', content)):
            target = match.group(1).strip().split(' "', 1)[0].strip('<>')
            url = urlsplit(target)
            if url.scheme or url.netloc or not url.path:
                continue
            links += 1
            resolved = (path.parent / unquote(url.path)).resolve()
            try:
                relative = resolved.relative_to(ROOT)
            except ValueError:
                errors.append(f'{path.relative_to(ROOT)}: link leaves repository: {target}')
                continue
            local_only = relative.parts[0] in ('reports', 'dist', '.venv') or (
                RAW in relative.parents and relative != RAW / 'sha256.json')
            if local_only:
                errors.append(f'{path.relative_to(ROOT)}: local-only artifact should be a code path, not a link: {target}')
            elif not resolved.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing link target: {target}')
    for path in sorted((ROOT / 'examples').glob('*.py')):
        snippets += 1
        try:
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path.relative_to(ROOT)))
        except SyntaxError as exc:
            errors.append(f'{path.relative_to(ROOT)}: {exc.msg}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Checked {len(paths)} Markdown files, {links} local links and {snippets} Python examples.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
