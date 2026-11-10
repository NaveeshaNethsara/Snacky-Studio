import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from run import find_running_app


class LauncherTests(unittest.TestCase):
    def test_reuses_a_running_snacky_server_without_startup_recovery(self):
        def response(url, timeout):
            if ':8000/' in url:
                raise URLError('Connection refused')
            return io.BytesIO(json.dumps({'application': 'snacky-studio', 'status': 'ok'}).encode())
        with patch('run.urlopen', side_effect=response):
            self.assertEqual(find_running_app([8000, 8125]), 'http://127.0.0.1:8125')

    def test_an_unrelated_local_service_is_not_reused(self):
        with patch('run.urlopen', return_value=io.BytesIO(json.dumps({'application': 'other', 'status': 'ok'}).encode())):
            self.assertIsNone(find_running_app([8000]))
