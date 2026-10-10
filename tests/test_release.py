"""Data-free regression tests for public-release safeguards."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_release', ROOT/'tools/check_release.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ReleaseTests(unittest.TestCase):
    def test_patient_file_blocked(self):
        self.assertTrue(check.content_issues('data/patients.csv', b'stay_id,value\n'))

    def test_binary_model_blocked(self):
        self.assertTrue(check.content_issues('model.rds', b'\x00\xff'))

    def test_secret_blocked(self):
        token = ('gh'+'p_'+'x'*36).encode()
        self.assertTrue(check.content_issues('config.py', token))

    def test_password_blocked(self):
        content = ('pass'+'word = '+repr('test-only-value')).encode()
        self.assertTrue(check.content_issues('config.py', content))

    def test_inline_password_blocked(self):
        content = ('connect(pass'+'word='+repr('test-only-value')+')').encode()
        self.assertTrue(check.content_issues('config.py', content))

    def test_literal_id_blocked(self):
        # Independently invented test identifier, not a database record.
        self.assertTrue(check.content_issues('query.sql', b'SELECT 1 WHERE stay_id = 123;'))

    def test_parameterized_sql_allowed(self):
        self.assertEqual(check.content_issues('query.sql', b'SELECT stay_id FROM t WHERE stay_id=any(%s);'), [])

    def test_invalid_python_blocked(self):
        self.assertTrue(check.content_issues('broken.py', b'def :'))


if __name__ == '__main__':
    unittest.main()
