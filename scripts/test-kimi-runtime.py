#!/usr/bin/env python3
"""Exercise the documented Kimi helper with a synthetic CLI only (stdlib/POSIX)."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, signal, subprocess, sys, time
args = sys.argv[1:]
skills = pathlib.Path(args[args.index('--skills-dir') + 1])
record = {'cwd': os.getcwd(), 'args': args, 'skills_absolute': skills.is_absolute(),
          'skills_empty': skills.is_dir() and not list(skills.iterdir()), 'home': os.environ['HOME']}
pathlib.Path(os.environ['KIMI_TEST_RECORD']).write_text(json.dumps(record))
mode = os.environ.get('KIMI_TEST_MODE', 'normal')
if mode in ('descendant', 'normal-child'):
    subprocess.Popen([sys.executable, '-c', "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(2.5); pathlib.Path(sys.argv[1]).write_text('late')", os.environ['KIMI_TEST_CANARY']])
if mode == 'ignore-alarm':
    signal.signal(signal.SIGALRM, signal.SIG_IGN)
if mode in ('descendant', 'ignore-alarm'):
    time.sleep(3)
print('synthetic answer', flush=True)
sys.exit(int(os.environ.get('KIMI_TEST_RC', '0')))
'''


class KimiRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='kimi-runtime-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'kimi'
        fake.write_text(FAKE.replace('#!/usr/bin/env python3', '#!' + sys.executable, 1), encoding='utf-8')
        fake.chmod(0o700)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.work = self.base / 'work'
        self.work.mkdir()
        (self.work / 'tmp').mkdir()
        self.record = self.base / 'record.json'
        self.canary = self.base / 'canary'
        self.env = {**os.environ, 'PATH': str(self.bin) + os.pathsep + '/usr/bin:/bin',
                    'HOME': str(self.home), 'TMPDIR': str(self.base),
                    'HEADLESS_RELAY_ROOT': str(ROOT), 'HEADLESS_RELAY_KIMI_TIMEOUT_SECONDS': '1',
                    'KIMI_TEST_RECORD': str(self.record), 'KIMI_TEST_CANARY': str(self.canary)}
        for name in ('HEADLESS_RELAY_KIMI_MODEL', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_CEILING_DIRECTORIES'):
            self.env.pop(name, None)
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        match = re.search(r'^kimi_relay\(\) \(\n.*?^\)\n', text, re.M | re.S)
        self.assertIsNotNone(match, 'documented helper must exist')
        assert match is not None
        self.helper = match.group()

    def run_helper(self, shell='sh', args=None, env=None):
        return subprocess.run([shell, '-c', self.helper + '\nkimi_relay "$@"', 'test',
                               *(args if args is not None else ['literal $x `cmd`\nsecond line'])],
                              env={**self.env, **(env or {})}, cwd=self.work,
                              capture_output=True, text=True, timeout=7)

    def test_exact_argv_empty_absolute_skills_and_cleanup(self):
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                result = self.run_helper(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                row = json.loads(self.record.read_text())
                self.assertTrue(row['skills_absolute'])
                self.assertTrue(row['skills_empty'])
                self.assertEqual(row['args'][row['args'].index('-p') + 1], 'literal $x `cmd`\nsecond line')
                self.assertEqual(row['args'][row['args'].index('-m') + 1], 'kimi-code/k3')
                self.assertEqual(row['home'], str(self.home))
                self.assertFalse(Path(row['cwd']).exists())

    def test_relative_tmpdir(self):
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                result = self.run_helper(shell, env={'TMPDIR': 'tmp'})
                self.assertEqual(result.returncode, 0, result.stderr)
                row = json.loads(self.record.read_text())
                self.assertTrue(row['skills_absolute'], row)
                self.assertTrue(row['skills_empty'], row)
                self.assertFalse(Path(row['cwd']).exists())

    def test_physical_git_ancestor_ignores_discovery_environment(self):
        # A .git file is also a repository/worktree boundary; no actual git CLI is needed.
        (self.base / '.git').write_text('gitdir: deliberately irrelevant')
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                result = self.run_helper(shell, env={'GIT_CEILING_DIRECTORIES': str(self.base),
                                                    'GIT_DIR': str(self.base / 'absent')})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.record.exists(), 'CLI must not run under physical .git ancestor')

    def test_timeout_ignoring_alarm(self):
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                start = time.monotonic()
                result = self.run_helper(shell, env={'KIMI_TEST_MODE': 'ignore-alarm'})
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertLess(time.monotonic() - start, 2.5)

    def test_timeout_kills_term_ignoring_descendant(self):
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                self.canary.unlink(missing_ok=True)
                result = self.run_helper(shell, env={'KIMI_TEST_MODE': 'descendant'})
                # Allow the finite fixture to finish even on RED, without signalling reused PIDs.
                time.sleep(2.7)
                self.assertFalse(self.canary.exists(), 'descendant wrote after helper returned')
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertFalse(Path(json.loads(self.record.read_text())['cwd']).exists())

    def test_normal_leader_exit_also_cancels_descendants(self):
        result = self.run_helper(env={'KIMI_TEST_MODE': 'normal-child'})
        time.sleep(2.7)
        self.assertFalse(self.canary.exists(), 'leader exit left a writing descendant')
        self.assertEqual(result.returncode, 0, result.stderr)

    def lifecycle_fixture(self):
        # Synchronize leader exit with a ready descendant and cleanup with its TERM.
        fake = self.bin / 'kimi'
        fake.write_text('#!' + sys.executable + '''
import os, pathlib, subprocess, sys, time
child = """import os,pathlib,signal,time
ready=pathlib.Path(os.environ['KIMI_TEST_READY'])
term=pathlib.Path(os.environ['KIMI_TEST_TERM'])
def on_term(*_): term.write_text('term')
signal.signal(signal.SIGTERM,on_term)
ready.write_text('ready')
time.sleep(2.5)
pathlib.Path(os.environ['KIMI_TEST_CANARY']).write_text('late')
"""
subprocess.Popen([sys.executable,'-c',child])
while not pathlib.Path(os.environ['KIMI_TEST_READY']).exists(): time.sleep(.002)
''')
        return {**self.env, 'KIMI_TEST_READY': str(self.base / 'ready'),
                'KIMI_TEST_TERM': str(self.base / 'term'),
                'HEADLESS_RELAY_KIMI_TIMEOUT_SECONDS': '5'}

    def test_inherited_ignored_sigchld_preserves_group_ownership(self):
        env = self.lifecycle_fixture()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/kimi_relay.py'), 'prompt'],
                                env=env, cwd=self.work, capture_output=True, text=True,
                                preexec_fn=lambda: signal.signal(signal.SIGCHLD, signal.SIG_IGN), timeout=6)
        time.sleep(2.7)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.canary.exists(), 'auto-reaped leader left a writing descendant')

    def test_cleanup_phase_signal_is_not_success(self):
        env = self.lifecycle_fixture()
        proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/kimi_relay.py'), 'prompt'],
                                env=env, cwd=self.work, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 3
        marker = Path(env['KIMI_TEST_TERM'])
        while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.002)
        ready = marker.exists()
        if ready:
            proc.send_signal(signal.SIGTERM)
        _, stderr = proc.communicate(timeout=5)
        self.assertTrue(ready, 'cleanup grace phase not reached')
        self.assertEqual(proc.returncode, 143, stderr.decode())
        time.sleep(2.7)
        self.assertFalse(self.canary.exists())

    def test_signals_during_temporary_directory_exit(self):
        # Inject the cancellation into the context manager's exit, after leader cleanup.
        script = ROOT / 'scripts/kimi_relay.py'
        wrapper = '''import importlib.util, os, signal, sys
spec=importlib.util.spec_from_file_location('relay',sys.argv[1])
module=importlib.util.module_from_spec(spec)
sys.dont_write_bytecode=True
spec.loader.exec_module(module)
original=module.tempfile.TemporaryDirectory
class InterruptedExit(original):
    def __exit__(self,*args):
        result=super().__exit__(*args)
        os.kill(os.getpid(),int(os.environ['KIMI_TEST_SIGNAL']))
        return result
module.tempfile.TemporaryDirectory=InterruptedExit
sys.argv=['kimi_relay.py','prompt']
sys.exit(module.main())
'''
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig):
                result = subprocess.run([sys.executable, '-c', wrapper, str(script)],
                                        env={**self.env, 'KIMI_TEST_SIGNAL': str(int(sig))},
                                        cwd=self.work, capture_output=True, timeout=6)
                self.assertEqual(result.returncode, 128 + sig, result.stderr)

    def test_model_precedence_format_and_nonzero(self):
        result = self.run_helper(args=['prompt', 'opaque/model', 'stream-json'],
                                 env={'HEADLESS_RELAY_KIMI_MODEL': 'other/model', 'KIMI_TEST_RC': '7'})
        self.assertEqual(result.returncode, 7, result.stderr)
        row = json.loads(self.record.read_text())
        self.assertEqual(row['args'][row['args'].index('-m') + 1], 'opaque/model')
        self.assertEqual(row['args'][-1], 'stream-json')
        self.assertFalse(Path(row['cwd']).exists())
        result = self.run_helper(env={'HEADLESS_RELAY_KIMI_MODEL': 'other/model'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('other/model', json.loads(self.record.read_text())['args'])

    def test_bad_input_never_runs_cli(self):
        for args, extra in (([], {}), (['p', 'm', 'bad'], {}), (['p'], {'HEADLESS_RELAY_KIMI_TIMEOUT_SECONDS': '0'}),
                            (['p'], {'HEADLESS_RELAY_KIMI_TIMEOUT_SECONDS': '1.5'}),
                            (['p'], {'TMPDIR': str(self.base / 'missing')}),
                            (['p'], {'HEADLESS_RELAY_ROOT': str(self.base / 'missing')})):
            with self.subTest(args=args, extra=extra):
                result = self.run_helper(args=args, env=extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.record.exists())

    def test_absolute_installed_skill_root_with_spaces(self):
        install = self.base / 'installed skill'
        (install / 'scripts').mkdir(parents=True)
        (install / 'scripts/kimi_relay.py').write_bytes((ROOT / 'scripts/kimi_relay.py').read_bytes())
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                result = self.run_helper(shell, env={'HEADLESS_RELAY_ROOT': str(install)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(self.record.read_text())['skills_empty'])

    def test_supervisor_signals_cancel_descendants(self):
        # Test the shipped executable directly: the shell helper execs this supervisor.
        script = ROOT / 'scripts/kimi_relay.py'
        self.assertTrue(script.is_file(), 'Kimi-owned supervisor is required')
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig):
                self.record.unlink(missing_ok=True)
                self.canary.unlink(missing_ok=True)
                proc = subprocess.Popen([sys.executable, str(script), 'prompt'],
                                        env={**self.env, 'KIMI_TEST_MODE': 'descendant'}, cwd=self.work,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                deadline = time.monotonic() + 3
                while not self.record.exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(self.record.exists(), 'synthetic CLI did not start')
                time.sleep(.1)
                proc.send_signal(sig)
                _, stderr = proc.communicate(timeout=4)
                time.sleep(2.7)
                self.assertEqual(proc.returncode, 128 + sig, stderr.decode())
                self.assertFalse(self.canary.exists())
                self.assertFalse(Path(json.loads(self.record.read_text())['cwd']).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
