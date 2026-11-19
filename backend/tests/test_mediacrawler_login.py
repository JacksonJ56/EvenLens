import importlib.util
from pathlib import Path
import tempfile
import unittest

from dotenv import dotenv_values

module_spec = importlib.util.spec_from_file_location("eventlens_login", Path(__file__).parents[1] / "scripts/mediacrawler_login.py")
login = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(login)


class LoginTests(unittest.TestCase):
    def test_only_mobile_weibo_cookies_are_used(self):
        header = login.mobile_cookie_header([
            {"domain": ".weibo.cn", "name": "SUB", "value": "test-session"},
            {"domain": ".weibo.com", "name": "PC", "value": "not-mobile"},
            {"domain": "weibo.cn.evil.org", "name": "other", "value": "not-allowed"},
            {"domain": ".weibo.cn", "name": "bad", "value": "bad\r\nvalue"},
        ])
        self.assertEqual(header, "SUB=test-session")

    def test_save_session_preserves_other_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text("DEEPSEEK_API_KEY=test-not-real\nMEDIACRAWLER_AUTHORIZED=true\n")
            login.save_session(env, "SUB=test; sample=contains'quote")
            values = dotenv_values(env)
            self.assertEqual(values["DEEPSEEK_API_KEY"], "test-not-real")
            self.assertEqual(values["MEDIACRAWLER_COOKIES_WB"], "SUB=test; sample=contains'quote")
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                login.save_session(env, "")
