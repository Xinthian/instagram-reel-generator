import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wake_codespace", ROOT / "scripts/wake-codespace.py")
WAKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WAKE)


class HealthChecks(unittest.TestCase):
    def test_only_exact_success_is_healthy(self):
        self.assertTrue(WAKE.health_ok('{"ok":true}\n200'))
        for output in ['<html>Login</html>\n200', '{"ok":false}\n200', '{"ok":1}\n200', '{"ok":true}\n302', '{"ok":true}\n503', '[]\n200', '{"ok":true}']:
            with self.subTest(output=output):
                self.assertFalse(WAKE.health_ok(output))


class SetupTests(unittest.TestCase):
    def test_generates_private_configuration_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/setup-env.py', root / 'scripts/setup-env.py')
            shutil.copyfile(ROOT / '.env.example', root / '.env.example')
            command = [sys.executable, str(root / 'scripts/setup-env.py')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            content = (root / '.env').read_text()
            self.assertNotIn("REEL_APP_PASSWORD", content)
            self.assertEqual(stat.S_IMODE((root / '.env').stat().st_mode), 0o600)
            self.assertIn('OPENROUTER_API_KEY=\n', content)
            self.assertIn(f'REEL_UID={os.getuid()}\n', content)
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual((root / '.env').read_text(), content)



class WakeScriptTests(unittest.TestCase):
    def run_wake(self, health, visibility_fails=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = root / 'gh'
            mock.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as stream: stream.write(json.dumps(args)+'\\n')
if args[:2] == ['codespace', 'list']:
    print(json.dumps([{'name':'reel-generator-test', 'displayName':'reel-generator'}]))
elif args[:2] == ['api', '--method']:
    Path(os.environ['MOCK_STARTED']).touch()
elif args[0] == 'api':
    print(json.dumps({'state':'Available' if Path(os.environ['MOCK_STARTED']).exists() else 'Shutdown'}))
elif args[:3] == ['codespace', 'ports', 'visibility']:
    sys.exit(1 if os.environ.get('MOCK_VISIBILITY_FAIL') == '1' else 0)
elif args[:2] == ['codespace', 'ssh']:
    sys.stdout.write(os.environ['MOCK_HEALTH'])
else:
    sys.exit(2)
''')
            mock.chmod(0o755)
            environment = dict(os.environ, PATH=directory + os.pathsep + os.environ['PATH'], MOCK_LOG=str(root / 'log'), MOCK_STARTED=str(root / 'started'), MOCK_HEALTH=health, MOCK_VISIBILITY_FAIL='1' if visibility_fails else '0', WAKE_TIMEOUT_SECONDS='0.4', WAKE_POLL_SECONDS='0.01')
            environment.pop('CODESPACE_NAME', None)
            result = subprocess.run(['bash', str(ROOT / 'scripts/wake-codespace.sh')], env=environment, capture_output=True, text=True, timeout=5)
            self.assertTrue(
                (root / 'log').exists(),
                f"Mock gh was never invoked (exit {result.returncode}). stdout={result.stdout!r}; stderr={result.stderr!r}",
            )
            calls = [json.loads(line) for line in (root / 'log').read_text().splitlines()]
            return result, calls

    def test_wake_enforces_private_access_and_checks_ssh_health(self):
        result, calls = self.run_wake('{"ok":true}\n200')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ready (private', result.stdout)
        self.assertIn(['api', '--method', 'POST', '/user/codespaces/reel-generator-test/start'], calls)
        self.assertIn(['codespace', 'ports', 'visibility', '7008:private', '-c', 'reel-generator-test'], calls)
        self.assertTrue(any(call[:2] == ['codespace', 'ssh'] and '127.0.0.1:7008/api/health' in call[-1] for call in calls))
        self.assertFalse(any(call[0] == 'api' and call[-1].endswith('/start') and '--method' not in call for call in calls))

    def test_failed_and_login_health_never_report_ready(self):
        for health in ['{"ok":false}\n200', '<html>Login</html>\n200', '{"ok":true}\n302']:
            with self.subTest(health=health):
                result, _ = self.run_wake(health)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Ready', result.stdout)
                self.assertIn('Timed out', result.stderr)

    def test_visibility_failure_never_reports_ready(self):
        result, calls = self.run_wake('{"ok":true}\n200', visibility_fails=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Ready', result.stdout)
        self.assertFalse(any(call[:2] == ['codespace', 'ssh'] for call in calls))


if __name__ == '__main__':
    unittest.main()
