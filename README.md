# encoding-claim-audit

Version 0.1.0. Offline static audit of documented UTF-8 and Unicode claims
against Python text file I/O. Python >=3.9; no runtime dependencies.
Audited code is never executed and no network requests are made.

## Usage

```sh
python3 -m pip install .
encoding-claim-audit [path]
encoding-claim-audit ./project --json --fail-on HIGH
encoding-claim-audit ./project --ignore documented-encoding-claim-false-test-only
encoding-claim-audit --version
```

Path defaults to `.`. `--verbose` prints verified claim notes and source counts.
`--json` emits findings, verified_claims, and summary. Each finding has a family,
rule, severity, message, and evidence items with path, line, and kind.
Exit codes: 0 PASS at the selected threshold, 2 FAIL, 1 usage/input error.
The default threshold is MEDIUM. `--fail-on HIGH` still prints MEDIUM findings.
Unknown ignore rules are input errors. `--ignore RULE,...` accepts:

- `documented-encoding-claim-false`: HIGH for production evidence or no source.
- `documented-encoding-claim-false-test-only`: MEDIUM for test-only evidence.

Each family produces at most one finding. Production evidence takes precedence.
Ignored findings are omitted, not relabeled as verified.

## Scope and limitations

Claims come from root README.md and docs/**/*.md prose, including inline code.
Backtick and tilde fenced code is excluded; sentences containing negation are
suppressed. Positive sentences elsewhere can independently establish a claim.
UTF-8, utf8, utf_8, and Unicode are recognized case-insensitively.

AST checks cover open/io.open, codecs.open, io.TextIOWrapper, and read_text/
write_text methods. Missing or non-UTF-8 literal encodings are evidence.
Standard open positional encoding and codecs.open third positional encoding
are recognized; Path methods and TextIOWrapper require keyword encoding.
Binary I/O is excluded. Tests are identified by tests/test/fixtures directory
components. examples directories and symlinks are skipped. Only Python source
and Markdown documentation are read; .env contents are never opened.
No claims yields empty findings and verified claims. No Python source yields
HIGH per family. No production text I/O makes the claim moot, not falsified.

This is static pattern matching, not semantic judgement. Dead code counts.
Variable modes/encodings are skipped as unknown. Dynamic file opens are missed.
Alias tracking is per-file only; shadowing and reassignment are not resolved.
Text method matching does not infer receiver types and may flag unrelated methods.
Negation is conservative and sentence based, so unrelated negative words can
suppress claims. Clean results with unknown encodings are qualified rather than
proof of runtime behavior. Source must be UTF-8 (optional BOM), docs UTF-8;
malformed or unreadable input yields exit 1.

## Differentiation

- privacy-claim-audit: network/telemetry evidence, never text encodings.
- config-claim-audit: documented default values, never encoding arguments.
- readme-claim-audit: install/flag/link/version, never encoding.
- bandit/ruff: code issues, never documentation promises.
- file/chardet: actual bytes on disk, never documentation versus code truth.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

The source distribution includes tests and good/bad/testonly fixtures, including
a marker-only .env read guard. Licensed under MIT.
