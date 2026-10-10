"""Check an explicit code-only allowlist before publishing. No database access."""
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTROL = {'.gitignore', 'PUBLIC_FILES.json'}
BLOCKED_SUFFIXES = {
    '.csv', '.tsv', '.parquet', '.rds', '.rdata', '.rda', '.pkl', '.pickle',
    '.feather', '.sqlite', '.db', '.zip', '.gz', '.7z', '.docx', '.pdf',
    '.png', '.jpg', '.tiff', '.xlsx', '.ipynb', '.log', '.dump', '.bak',
}
BLOCKED_PARTS = {'data', 'local_only', 'results', 'outputs', '.env', '.pgpass',
                 'pgpass.conf', 'node_modules', '.venv'}
SECRET_PATTERNS = [
    r'\bgh[pousr]_[A-Za-z0-9]{20,}\b',
    r'\bgithub_pat_[A-Za-z0-9_]{20,}\b',
    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    r'postgres(?:ql)?://[^\s:/]+:[^\s@]+@',
    r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    r'(?i)\b(?:password|passwd|api_key|access_token|secret)\s*[:=]\s*[\"\x27][^\"\x27]+[\"\x27]',
]


def content_issues(rel, raw):
    issues = []
    p = Path(rel)
    if p.suffix.lower() in BLOCKED_SUFFIXES or any(x.lower() in BLOCKED_PARTS for x in p.parts):
        issues.append('restricted/generated file type or location')
    if len(raw) > 1_000_000:
        issues.append('unexpectedly large source file')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return issues + ['non-UTF-8 or binary content']
    if '\x00' in text:
        issues.append('binary/NUL content')
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, text):
            issues.append('possible credential (value not printed)')
    if re.search(r'(?i)\b[A-Z]:[/\\](?:Users|codexdoing|anaconda)', text):
        issues.append('private absolute workspace path')
    if p.suffix.lower() == '.sql' and re.search(
        r'(?i)\b(?:subject_id|stay_id|hadm_id|patientunitstayid|hospitalid)\s*(?:=\s*\d+|in\s*\(\s*\d+)', text
    ):
        issues.append('literal patient/stay/hospital identifier in SQL')
    if p.suffix == '.py':
        try:
            ast.parse(text, filename=rel)
        except SyntaxError:
            issues.append('invalid Python syntax')
    return issues


def ignored_for_scan(p):
    return '.git' in p.parts or '__pycache__' in p.parts


def main():
    spec = json.loads((ROOT/'PUBLIC_FILES.json').read_text(encoding='utf-8'))
    expected = spec['files']
    actual = {p.relative_to(ROOT).as_posix(): p for p in ROOT.rglob('*')
              if p.is_file() and not ignored_for_scan(p.relative_to(ROOT))}
    errors = []
    for name in set(actual) - set(expected) - CONTROL:
        errors.append(f'{name}: not in reviewed allowlist')
    for name in set(expected) - set(actual):
        errors.append(f'{name}: missing reviewed file')
    for name, p in sorted(actual.items()):
        if p.is_symlink():
            errors.append(f'{name}: symbolic links are not allowed')
            continue
        if not p.resolve().is_relative_to(ROOT.resolve()):
            errors.append(f'{name}: outside repository boundary')
            continue
        raw = p.read_bytes()
        errors.extend(f'{name}: {e}' for e in content_issues(name, raw))
        if name in expected and hashlib.sha256(raw).hexdigest() != expected[name]:
            errors.append(f'{name}: changed since source review')
    if (ROOT/'.git').exists():
        staged = subprocess.run(['git', 'diff', '--cached', '--name-only', '-z'], cwd=ROOT,
                                capture_output=True, check=True).stdout.decode('utf-8').split('\0')
        for name in filter(None, staged):
            if name not in set(expected) | CONTROL:
                errors.append(f'{name}: unapproved staged path')
                continue
            result = subprocess.run(['git', 'show', ':'+name], cwd=ROOT, capture_output=True)
            if result.returncode:
                errors.append(f'{name}: staged deletion or unreadable blob')
                continue
            errors.extend(f'{name} (staged): {e}' for e in content_issues(name, result.stdout))
            if name in expected and hashlib.sha256(result.stdout).hexdigest() != expected[name]:
                errors.append(f'{name}: staged content differs from reviewed content')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'PASS: {len(actual)} reviewed code/documentation files; no unlisted artifacts.')
    print('Automated checks are safeguards, not a de-identification or legal certification.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
