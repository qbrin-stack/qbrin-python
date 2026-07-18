"""Offline SDK tests — a stub transport, no network. Run: python -m unittest discover tests"""

import json
import os
import shutil
import tempfile
import unittest

from qbrin import (
    AuthenticationError,
    FeatureDisabledError,
    Qbrin,
    RateLimitError,
    QbrinError,
)


def stub(responses):
    """A transport that pops queued (status, headers, body_dict) tuples and records calls."""
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "body": body})
        status, hdrs, payload = responses.pop(0)
        return status, hdrs, json.dumps(payload).encode("utf-8")

    transport.calls = calls
    return transport


VERIFIED = {
    "decision": "verified",
    "reason": "gates_passed_verifier_ok",
    "explanation": "Every claim is cited and verified.",
    "answer": "[1] The refund limit for Support Managers is $300.",
    "evidence": [{"n": 1, "documentId": "d1", "source": "postgres", "snippet": "limit: $300"}],
    "claims": [{"claim": "the limit is $300", "citations": ["1"], "supported": True, "reason": "stated in [1]"}],
    "freshness": {"checkedAt": "2026-07-17T12:00:00.000Z", "liveEvidenceCount": 1,
                  "oldestEvidence": "2026-06-01T00:00:00.000Z", "newestEvidence": "2026-07-17T12:00:00.000Z"},
    "trust": {"decision": "allow", "level": "verified"},
}


class TestVerify(unittest.TestCase):
    def make(self, responses):
        t = stub(responses)
        return Qbrin(api_key="qbrin_test", transport=t), t

    def test_verified_result(self):
        qb, t = self.make([(200, {}, VERIFIED)])
        v = qb.verify("Can I refund $500 for ORD-200?")
        self.assertTrue(v.is_verified)
        self.assertEqual(v.evidence[0].document_id, "d1")
        self.assertIn("Authorization", t.calls[0]["headers"])
        self.assertTrue(t.calls[0]["headers"]["Authorization"].startswith("Bearer qbrin_"))
        self.assertTrue(t.calls[0]["url"].endswith("/verify"))

    def test_need_more_evidence(self):
        body = {"decision": "need_more_evidence", "reason": "not_covered_by_sources",
                "explanation": "…", "answer": None, "evidence": [], "trust": None}
        qb, _ = self.make([(200, {}, body)])
        v = qb.verify("Who is the CFO of Nimbus?")
        self.assertTrue(v.needs_more_evidence)
        self.assertIsNone(v.answer)
        self.assertIsNone(v.claims)
        self.assertIsNone(v.freshness)  # absent field parses as None, no crash

    def test_claims_and_freshness_parse(self):
        qb, _ = self.make([(200, {}, VERIFIED)])
        v = qb.verify("refund limit?")
        self.assertEqual(len(v.claims), 1)
        self.assertTrue(v.claims[0].supported)
        self.assertEqual(v.claims[0].citations, ["1"])
        self.assertTrue(v.freshness.used_live_evidence)
        self.assertEqual(v.freshness.newest_evidence, "2026-07-17T12:00:00.000Z")

    def test_rejected(self):
        body = {"decision": "rejected", "reason": "premise_not_supported",
                "explanation": "…", "answer": None, "evidence": [], "trust": None}
        qb, _ = self.make([(200, {}, body)])
        self.assertTrue(qb.verify("Why did the launch move to March?").is_rejected)

    def test_k_is_passed(self):
        qb, t = self.make([(200, {}, VERIFIED)])
        qb.verify("q", k=12)
        self.assertEqual(json.loads(t.calls[0]["body"])["k"], 12)

    def test_401_raises_authentication_error(self):
        qb, _ = self.make([(401, {}, {"error": "bad token"})])
        with self.assertRaises(AuthenticationError):
            qb.verify("q")

    def test_404_on_verify_maps_to_feature_disabled(self):
        qb, _ = self.make([(404, {}, {"error": "Not found."})])
        with self.assertRaises(FeatureDisabledError):
            qb.verify("q")

    def test_429_retries_then_raises_with_retry_after(self):
        qb, t = self.make([
            (429, {"Retry-After": "0"}, {"error": "rate_limited"}),
            (429, {"Retry-After": "0"}, {"error": "rate_limited"}),
            (429, {"Retry-After": "7"}, {"error": "rate_limited"}),
        ])
        with self.assertRaises(RateLimitError) as ctx:
            qb.verify("q")
        self.assertEqual(len(t.calls), 3)  # initial + 2 retries (max_retries default)
        self.assertEqual(ctx.exception.retry_after, 7.0)

    def test_5xx_retry_then_success(self):
        qb, t = self.make([(503, {}, {"error": "warming"}), (200, {}, VERIFIED)])
        self.assertTrue(qb.verify("q").is_verified)
        self.assertEqual(len(t.calls), 2)

    def test_http_base_url_rejected(self):
        with self.assertRaises(QbrinError):
            Qbrin(api_key="qbrin_x", base_url="http://evil.example.com/api")

    def test_localhost_http_allowed(self):
        Qbrin(api_key="qbrin_x", base_url="http://localhost:4000/api")


class TestAskSearch(unittest.TestCase):
    def test_ask(self):
        body = {"answer": "[1] Two weeks.", "citations": [{"n": 1, "documentId": "d9"}],
                "coveredBySnapshot": True}
        t = stub([(200, {}, body)])
        a = Qbrin(api_key="qbrin_t", transport=t).ask("Notice period?")
        self.assertEqual(a.citations[0].document_id, "d9")
        self.assertTrue(a.covered_by_map)

    def test_search_builds_query_string(self):
        t = stub([(200, {}, {"results": []})])
        Qbrin(api_key="qbrin_t", transport=t).search("refund policy", limit=5)
        self.assertIn("/search?", t.calls[0]["url"])
        self.assertIn("limit=5", t.calls[0]["url"])
        self.assertEqual(t.calls[0]["method"], "GET")


class TestCredentials(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["QBRIN_HOME"] = self._tmp
        os.environ.pop("QBRIN_API_KEY", None)
        os.environ.pop("QBRIN_BASE_URL", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_key_anywhere_raises_clear_error(self):
        with self.assertRaises(QbrinError) as ctx:
            Qbrin()
        self.assertIn("qbrin login", str(ctx.exception))

    def test_reads_env_key(self):
        os.environ["QBRIN_API_KEY"] = "qbrin_from_env"
        qb = Qbrin(transport=stub([(200, {}, VERIFIED)]))
        self.assertTrue(qb.verify("q").is_verified)

    def test_reads_credentials_file(self):
        from qbrin.client import credentials_path
        p = credentials_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"token": "qbrin_from_file", "base_url": "https://app.qbrin.com/api"}))
        t = stub([(200, {}, VERIFIED)])
        qb = Qbrin(transport=t)
        self.assertTrue(qb.verify("q").is_verified)
        self.assertTrue(t.calls[0]["headers"]["Authorization"].endswith("qbrin_from_file"))

    def test_explicit_key_beats_env_and_file(self):
        os.environ["QBRIN_API_KEY"] = "qbrin_env"
        t = stub([(200, {}, VERIFIED)])
        qb = Qbrin(api_key="qbrin_explicit", transport=t)
        qb.verify("q")
        self.assertTrue(t.calls[0]["headers"]["Authorization"].endswith("qbrin_explicit"))


class TestCli(unittest.TestCase):
    def test_help_runs(self):
        from qbrin import cli
        self.assertEqual(cli.main(["help"]), 0)

    def test_unknown_command_nonzero(self):
        from qbrin import cli
        self.assertEqual(cli.main(["bogus"]), 1)


if __name__ == "__main__":
    unittest.main()
