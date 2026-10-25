"""Command line interface."""
import argparse
import json
import sys
from . import __version__
from .audit import RULE, TEST_RULE, audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, '%s: error: %s\n' % (self.prog, message))


def main(argv=None):
    parser = Parser(prog='encoding-claim-audit')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--fail-on', choices=('HIGH', 'MEDIUM'), default='MEDIUM')
    parser.add_argument('--ignore', default='', metavar='RULE,...')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    ignored = set(filter(None, args.ignore.split(',')))
    if ignored - {RULE, TEST_RULE}:
        parser.error('unknown ignored rule: ' + ', '.join(sorted(ignored - {RULE, TEST_RULE})))
    try:
        result = audit(args.path, ignored)
    except (OSError, ValueError, SyntaxError) as exc:
        print('encoding-claim-audit: ' + str(exc), file=sys.stderr)
        return 1
    failed = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings'])
    result['summary']['status'] = 'FAIL' if failed else 'PASS'
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result['summary']['status'])
        for finding in result['findings']:
            print('{severity} {rule} [{family}]: {message}'.format(**finding))
            for item in finding['evidence']:
                print('  {path}:{line}: {kind}'.format(**item))
        if args.verbose:
            for claim in result['verified_claims']:
                print('{family}: {note}'.format(**claim))
            print('Python files: ' + str(result['summary']['python_files']))
    return 2 if failed else 0
