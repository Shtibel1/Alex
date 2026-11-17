import socket
import unittest

import requests

from pricecompare import sources


class FakeResponse:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


class Script:
    """A fake requests method that raises or answers in a fixed order."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _request(method, sleeps):
    return sources._request(method, "https://portal.example/", sleep=sleeps.append)


class RequestRetryTest(unittest.TestCase):
    def test_uses_separate_connect_and_read_timeouts(self):
        method = Script(FakeResponse())
        sources._request(method, "https://portal.example/", sleep=lambda s: None, params={"a": 1})
        _, kwargs = method.calls[0]
        self.assertEqual(kwargs["timeout"], (sources.CONNECT_TIMEOUT, sources.READ_TIMEOUT))
        self.assertLess(sources.CONNECT_TIMEOUT, sources.READ_TIMEOUT)
        self.assertEqual(kwargs["params"], {"a": 1})

    def test_retries_slow_responses_then_succeeds(self):
        ok = FakeResponse()
        method = Script(requests.ReadTimeout(), FakeResponse(503), ok)
        sleeps = []
        self.assertIs(_request(method, sleeps), ok)
        self.assertEqual(sleeps, [2, 4])

    def test_gives_up_on_read_errors_after_all_attempts(self):
        method = Script(*[requests.ReadTimeout() for _ in range(sources.ATTEMPTS)])
        with self.assertRaises(requests.ReadTimeout):
            _request(method, [])
        self.assertEqual(len(method.calls), sources.ATTEMPTS)

    def test_unreachable_host_fails_fast(self):
        method = Script(*[requests.ConnectTimeout() for _ in range(sources.ATTEMPTS)])
        sleeps = []
        with self.assertRaises(requests.ConnectTimeout):
            _request(method, sleeps)
        self.assertEqual(len(method.calls), sources.CONNECT_ATTEMPTS)
        self.assertEqual(len(sleeps), sources.CONNECT_ATTEMPTS - 1)

    def test_connection_reset_mid_response_keeps_full_retries(self):
        aborted = requests.ConnectionError("Connection aborted.")
        method = Script(aborted, aborted, aborted, FakeResponse())
        result = _request(method, [])
        self.assertEqual(len(method.calls), 4)
        self.assertEqual(result.status_code, 200)

    def test_refused_connection_counts_as_unreachable(self):
        # A real refused connection: bind a port, then close it so nothing listens.
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        session = requests.Session()
        sleeps = []
        with self.assertRaises(requests.ConnectionError) as ctx:
            sources._request(session.get, f"http://127.0.0.1:{port}/", sleep=sleeps.append)
        self.assertTrue(sources._unreachable(ctx.exception))
        self.assertEqual(len(sleeps), sources.CONNECT_ATTEMPTS - 1)

    def test_unreachable_classification(self):
        self.assertTrue(sources._unreachable(requests.ConnectTimeout()))
        self.assertFalse(sources._unreachable(requests.ReadTimeout()))
        self.assertFalse(sources._unreachable(requests.ConnectionError("Connection aborted.")))
        self.assertFalse(sources._unreachable(requests.HTTPError("500")))


if __name__ == "__main__":
    unittest.main()
