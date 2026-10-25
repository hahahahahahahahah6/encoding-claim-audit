"""Offline documentation and AST encoding audit."""
import ast
import re
from pathlib import Path

RULE = 'documented-encoding-claim-false'
TEST_RULE = RULE + '-test-only'
FAMILIES = {'UTF-8': r'\butf[-_]?8\b', 'Unicode': r'\bunicode\b'}


def claims_in(text):
    """Return claim families in unfenced, non-negated prose."""
    prose = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            prose.append(line)
    result = set()
    for sentence in re.split(r'[.!?\n]+', '\n'.join(prose)):
        if re.search(r"\b(no|not|never|without)\b|\b(?:doesn’t|doesn't|cannot|can't)\b", sentence, re.I):
            continue
        for family, pattern in FAMILIES.items():
            if re.search(pattern, sentence, re.I):
                result.add(family)
    return result


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _name(node.value) + '.' + node.attr
    return ''


def inspect_source(text, path):
    """Return evidence and number of statically recognized text sites."""
    tree = ast.parse(text, filename=path)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name
    evidence = []
    sites = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        first, _, rest = name.partition('.')
        name = aliases.get(first, first) + ('.' + rest if rest else '')
        keywords = {k.arg: k.value for k in node.keywords}
        encoding = keywords.get('encoding')
        if name in ('open', 'io.open', 'builtins.open', 'codecs.open'):
            mode = keywords.get('mode', node.args[1] if len(node.args) > 1 else ast.Constant('r'))
            if not isinstance(mode, ast.Constant) or not isinstance(mode.value, str):
                continue
            if 'b' in mode.value:
                continue
            position = 2 if name == 'codecs.open' else 3
            if encoding is None and len(node.args) > position:
                encoding = node.args[position]
        elif name == 'io.TextIOWrapper' or (isinstance(node.func, ast.Attribute) and node.func.attr in ('read_text', 'write_text')):
            pass
        else:
            continue
        sites += 1
        if encoding is None:
            kind = 'missing-encoding'
        elif isinstance(encoding, ast.Constant):
            if isinstance(encoding.value, str) and encoding.value.lower() in ('utf-8', 'utf8', 'utf_8'):
                continue
            kind = 'wrong-encoding'
        else:
            continue
        evidence.append({'path': path, 'line': node.lineno, 'kind': kind})
    return evidence, sites


def audit(root, ignore=()):
    """Audit a directory without importing or executing its source."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError('input path must be a directory')
    claims = set()
    docs = [root / 'README.md']
    if (root / 'docs').is_dir() and not (root / 'docs').is_symlink():
        docs.extend((root / 'docs').rglob('*.md'))
    def safe(path):
        return not any(p.is_symlink() for p in [path] + list(path.parents) if p != root.parent)
    for path in docs:
        if path.is_file() and safe(path):
            claims.update(claims_in(path.read_text(encoding='utf-8')))
    if not claims:
        return {'findings': [], 'verified_claims': [], 'summary': {'claims': 0, 'findings': 0, 'python_files': 0}}
    production, testonly = [], []
    sources = sites = 0
    for path in sorted(root.rglob('*.py')):
        relative = path.relative_to(root)
        if not safe(path) or 'examples' in relative.parts:
            continue
        sources += 1
        evidence, count = inspect_source(path.read_text(encoding='utf-8-sig'), relative.as_posix())
        is_test = bool(set(relative.parts[:-1]) & {'tests', 'test', 'fixtures'})
        (testonly if is_test else production).extend(evidence)
        if not is_test:
            sites += count
    findings, verified = [], []
    for family in sorted(claims):
        if production or not sources:
            rule, severity, evidence = RULE, 'HIGH', production
            note = 'Production text I/O contradicts the claim.' if sources else 'No Python source files found.'
        elif testonly:
            rule, severity, evidence = TEST_RULE, 'MEDIUM', testonly
            note = 'Encoding evidence occurs only in tests or fixtures.'
        else:
            verified.append({'family': family, 'note': 'All recognized production text I/O carries UTF-8 encoding or an unknown encoding.' if sites else 'No production text I/O; claim is moot, not falsified.'})
            continue
        if rule not in ignore:
            findings.append({'rule': rule, 'severity': severity, 'family': family, 'message': note, 'evidence': evidence})
    return {'findings': findings, 'verified_claims': verified, 'summary': {'claims': len(claims), 'findings': len(findings), 'python_files': sources}}
