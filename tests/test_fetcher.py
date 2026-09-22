import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from scripts.update import Fetcher


def response(status, body=b'ok'):
    result = MagicMock()
    result.status_code = status
    result.headers = {}
    result.iter_content.return_value = [body]
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(
            f'HTTP {status}', response=result
        )
    return result


class FetcherRetryTests(unittest.TestCase):
    def fetcher(self, temp, retries=5):
        fetcher = Fetcher(0, allowed_hosts=['example.com'], max_retries=retries)
        fetcher.cache = Path(temp)
        return fetcher

    def test_retries_temporary_server_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            fetcher = self.fetcher(temp)
            fetcher.session.get = MagicMock(
                side_effect=[response(503), response(503), response(200)]
            )
            with patch('scripts.update.time.sleep') as sleep:
                self.assertEqual(fetcher.get('https://example.com/data'), b'ok')
            self.assertEqual(fetcher.session.get.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [0, 2, 0, 4, 0])

    def test_does_not_retry_permanent_not_found(self):
        with tempfile.TemporaryDirectory() as temp:
            fetcher = self.fetcher(temp)
            fetcher.session.get = MagicMock(return_value=response(404))
            with patch('scripts.update.time.sleep'):
                with self.assertRaises(requests.HTTPError):
                    fetcher.get('https://example.com/missing')
            self.assertEqual(fetcher.session.get.call_count, 1)

    def test_stops_after_five_retries(self):
        with tempfile.TemporaryDirectory() as temp:
            fetcher = self.fetcher(temp, retries=5)
            fetcher.session.get = MagicMock(side_effect=[response(503) for _ in range(6)])
            with patch('scripts.update.time.sleep'):
                with self.assertRaises(requests.HTTPError):
                    fetcher.get('https://example.com/unavailable')
            self.assertEqual(fetcher.session.get.call_count, 6)


if __name__ == '__main__':
    unittest.main()
