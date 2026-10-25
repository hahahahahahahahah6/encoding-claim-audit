import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from encoding_claim_audit.audit import audit, claims_in, inspect_source, RULE, TEST_RULE
from encoding_claim_audit.cli import main

FIXTURES = Path(__file__).parent / 'fixtures'


class AuditTests(unittest.TestCase):
    def source(self, code):
        return inspect_source(code, 'app.py')[0]

    def project(self, readme='UTF-8', source="open('x')", filename='app.py'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'README.md').write_text(readme, encoding='utf-8')
        if source is not None:
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding='utf-8')
        return root

    def cli(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                code = main(list(map(str, args)))
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_good(self):
        result = audit(FIXTURES / 'good')
        self.assertEqual(result['findings'], [])
        self.assertEqual(len(result['verified_claims']), 2)

    def test_bad(self):
        findings = audit(FIXTURES / 'bad')['findings']
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['severity'], 'HIGH')
        self.assertEqual([e['kind'] for e in findings[0]['evidence']], ['missing-encoding', 'wrong-encoding'])

    def test_testonly(self):
        self.assertEqual({f['severity'] for f in audit(FIXTURES / 'testonly')['findings']}, {'MEDIUM'})

    def test_good_cli(self):
        self.assertEqual(self.cli(FIXTURES / 'good')[0], 0)

    def test_bad_cli(self):
        self.assertEqual(self.cli(FIXTURES / 'bad')[0], 2)

    def test_testonly_cli(self):
        self.assertEqual(self.cli(FIXTURES / 'testonly')[0], 2)

    def test_high_threshold(self):
        code, output, _ = self.cli(FIXTURES / 'testonly', '--fail-on', 'HIGH')
        self.assertEqual(code, 0)
        self.assertIn('MEDIUM', output)

    def test_json(self):
        code, output, _ = self.cli(FIXTURES / 'bad', '--json')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)['summary']['status'], 'FAIL')

    def test_version(self):
        self.assertEqual(self.cli('--version')[:2], (0, '0.1.0\n'))

    def test_ignore_high(self):
        self.assertEqual(self.cli(FIXTURES / 'bad', '--ignore', RULE)[0], 0)

    def test_ignore_medium(self):
        self.assertEqual(self.cli(FIXTURES / 'testonly', '--ignore', TEST_RULE)[0], 0)

    def test_ignore_multiple(self):
        self.assertEqual(self.cli(FIXTURES / 'bad', '--ignore', RULE + ',' + TEST_RULE)[0], 0)

    def test_unknown_ignore(self):
        self.assertEqual(self.cli('--ignore', 'typo')[0], 1)

    def test_bad_option(self):
        self.assertEqual(self.cli('--no-such-option')[0], 1)

    def test_bad_threshold(self):
        self.assertEqual(self.cli('--fail-on', 'LOW')[0], 1)

    def test_bad_path(self):
        self.assertEqual(self.cli('/no/such/project')[0], 1)

    def test_verbose(self):
        self.assertIn('Python files:', self.cli(FIXTURES / 'good', '--verbose')[1])

    def test_default_path(self):
        previous = os.getcwd()
        try:
            os.chdir(FIXTURES / 'good')
            self.assertEqual(self.cli()[0], 0)
        finally:
            os.chdir(previous)

    def test_utf8_variant(self):
        self.assertEqual(claims_in('utf8'), {'UTF-8'})

    def test_utfunderscore_variant(self):
        self.assertEqual(claims_in('UTF_8'), {'UTF-8'})

    def test_unicode_case(self):
        self.assertEqual(claims_in('uNiCoDe'), {'Unicode'})

    def test_family_dedup(self):
        self.assertEqual(claims_in('UTF-8 utf8 utf_8'), {'UTF-8'})

    def test_inline_code(self):
        self.assertEqual(claims_in('Supports `UTF-8`'), {'UTF-8'})

    def test_backtick_fence(self):
        self.assertEqual(claims_in('```python\nUTF-8 Unicode\n```'), set())

    def test_tilde_fence(self):
        self.assertEqual(claims_in('~~~\nUTF-8\n~~~\nUnicode'), {'Unicode'})

    def test_fence_short_close(self):
        self.assertEqual(claims_in('````\n```\nUTF-8\n````'), set())

    def test_negated(self):
        self.assertEqual(claims_in('Does not support UTF-8. No Unicode support.'), set())

    def test_positive_sentence_after_negative(self):
        self.assertEqual(claims_in('No Unicode support. Supports UTF-8.'), {'UTF-8'})

    def test_no_claim(self):
        result = audit(self.project('A package.'))
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['verified_claims'], [])

    def test_no_source(self):
        self.assertEqual(len(audit(self.project('UTF-8 and Unicode', None))['findings']), 2)

    def test_unicode_evidence(self):
        self.assertEqual(audit(self.project('Unicode'))['findings'][0]['family'], 'Unicode')

    def test_moot(self):
        result = audit(self.project(source='x = 1'))
        self.assertIn('moot', result['verified_claims'][0]['note'])

    def test_docs_nested(self):
        root = self.project('A package.')
        doc = root / 'docs' / 'nested' / 'guide.md'
        doc.parent.mkdir(parents=True)
        doc.write_text('Unicode', encoding='utf-8')
        self.assertEqual(len(audit(root)['findings']), 1)

    def test_open_missing(self):
        self.assertEqual(self.source("open('x')")[0]['kind'], 'missing-encoding')

    def test_io_open(self):
        self.assertEqual(len(self.source("import io\nio.open('x')")), 1)

    def test_open_positional_encoding(self):
        self.assertEqual(self.source("open('x', 'r', -1, 'UTF-8')"), [])

    def test_binary(self):
        self.assertEqual(self.source("open('x', 'rb'); open('x', mode='wb+')"), [])

    def test_variable_mode(self):
        self.assertEqual(self.source("open('x', mode=mode)"), [])

    def test_variable_encoding(self):
        self.assertEqual(self.source("open('x', encoding=encoding)"), [])

    def test_text_modes(self):
        for mode in ('r', 'w', 'a', 'x', 'r+', 'w+', 'a+', 'x+'):
            with self.subTest(mode=mode):
                self.assertEqual(len(self.source("open('x', %r)" % mode)), 1)

    def test_codecs_positional(self):
        self.assertEqual(self.source("import codecs\ncodecs.open('x', 'r', 'utf8')"), [])

    def test_codecs_wrong_positional(self):
        self.assertEqual(self.source("import codecs\ncodecs.open('x', 'r', 'latin-1')")[0]['kind'], 'wrong-encoding')

    def test_codecs_missing(self):
        self.assertEqual(len(self.source("import codecs\ncodecs.open('x')")), 1)

    def test_codecs_keyword(self):
        self.assertEqual(self.source("import codecs\ncodecs.open('x', encoding='utf_8')"), [])

    def test_wrapper_missing(self):
        self.assertEqual(len(self.source('import io\nio.TextIOWrapper(stream)')), 1)

    def test_wrapper_wrong(self):
        self.assertEqual(self.source("import io\nio.TextIOWrapper(stream, encoding='ascii')")[0]['kind'], 'wrong-encoding')

    def test_wrapper_good(self):
        self.assertEqual(self.source("import io\nio.TextIOWrapper(stream, encoding='utf8')"), [])

    def test_path_methods(self):
        for method in ('read_text', 'write_text'):
            self.assertEqual(len(self.source("path.%s()" % method)), 1)

    def test_path_wrong(self):
        self.assertEqual(self.source("path.write_text('x', encoding='latin-1')")[0]['kind'], 'wrong-encoding')

    def test_path_variable(self):
        self.assertEqual(self.source('path.read_text(encoding=enc)'), [])

    def test_bytes(self):
        self.assertEqual(self.source("p.read_bytes(); p.write_bytes(b'x')"), [])

    def test_streams(self):
        self.assertEqual(self.source("import sys\nsys.stdin.read(); sys.stdout.write('x'); print('x', file=sys.stdout)"), [])

    def test_aliases(self):
        self.assertEqual(len(self.source('import io as streams\nfrom codecs import open as copen\nstreams.open("x")\ncopen("x")')), 2)

    def test_from_wrapper(self):
        self.assertEqual(len(self.source('from io import TextIOWrapper as W\nW(stream)')), 1)

    def test_symlink(self):
        root = self.project(source='x = 1')
        (root / 'linked.py').symlink_to(FIXTURES.resolve() / 'bad' / 'app.py')
        self.assertEqual(audit(root)['findings'], [])

    def test_symlink_directory(self):
        root = self.project(source='x = 1')
        (root / 'linked').symlink_to(FIXTURES.resolve() / 'bad', target_is_directory=True)
        self.assertEqual(audit(root)['findings'], [])

    def test_examples(self):
        self.assertEqual(audit(self.project(filename='examples/demo.py'))['summary']['python_files'], 0)

    def test_test_components(self):
        for directory in ('tests', 'test', 'fixtures'):
            self.assertEqual(audit(self.project(filename=directory + '/app.py'))['findings'][0]['severity'], 'MEDIUM')

    def test_production_wins(self):
        root = self.project()
        (root / 'tests').mkdir()
        (root / 'tests' / 'test_x.py').write_text("open('x')", encoding='utf-8')
        finding = audit(root)['findings'][0]
        self.assertEqual(finding['severity'], 'HIGH')
        self.assertEqual(len(finding['evidence']), 1)

    def test_env_never_read(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env':
                raise AssertionError('.env opened')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            code, output, error = self.cli(FIXTURES / 'bad', '--json')
        self.assertEqual(code, 2)
        self.assertNotIn('ENCODING_AUDIT_ENV_MUST_NEVER_BE_READ_73491', output + error)

    def test_none_encoding(self):
        self.assertEqual(self.source("open('x', encoding=None)")[0]['kind'], 'wrong-encoding')

    def test_no_claim_invalid_source(self):
        self.assertEqual(audit(self.project('No promises.', 'broken('))['findings'], [])

    def test_invalid_python(self):
        self.assertEqual(self.cli(self.project(source='def broken('))[0], 1)

    def test_module_entrypoint(self):
        result = subprocess.run([sys.executable, '-m', 'encoding_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))


if __name__ == '__main__':
    unittest.main()
