"""Deployment failure-path checks; no Docker daemon or network required."""
import os
import unittest
from unittest.mock import patch

import deploy_dev as deploy


class RequestTests(unittest.TestCase):
    def test_explicit_client_user_agent(self):
        from io import BytesIO
        with patch.object(deploy.urllib.request, "urlopen", return_value=BytesIO(b'{"ok": true}')) as opener:
            self.assertEqual(deploy.request("https://npm.example/api/tokens", "POST", {"identity": "user"}), {"ok": True})
        req = opener.call_args.args[0]
        self.assertEqual(req.get_header("User-agent"), "Flyio-Jenkins-Deploy/1.0")


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.host = {
            "forward_scheme": "http", "forward_host": "previous", "forward_port": 8080,
            "certificate_id": 42, "meta": {"nginx_online": True},
        }
        self.env = patch.dict(os.environ, {"CANDIDATE": "candidate"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_promotion(self, public_results, fail_first_write=False, fail_rollback=False):
        writes = []
        state = dict(self.host)

        def api(url, method="GET", payload=None, headers=None):
            if method == "PUT":
                writes.append(dict(payload))
                if fail_rollback and len(writes) == 2:
                    raise OSError("unavailable")
                state.update(payload)
                if fail_first_write and len(writes) == 1:
                    raise TimeoutError("uncertain write")
            return dict(state)

        with patch.object(deploy, "connect", return_value=("endpoint", {}, dict(self.host))), \
             patch.object(deploy, "request", side_effect=api), \
             patch.object(deploy, "verify_public", side_effect=public_results):
            error = None
            try:
                deploy.promote()
            except RuntimeError as exc:
                error = str(exc)
        return writes, state, error

    def test_success_only_changes_upstream(self):
        writes, state, error = self.run_promotion([None])
        self.assertIsNone(error)
        self.assertEqual(len(writes), 1)
        self.assertEqual(state["forward_host"], "candidate")
        self.assertEqual(state["certificate_id"], 42)
        self.assertEqual(set(writes[0]), {"forward_scheme", "forward_host", "forward_port"})

    def test_failed_public_check_restores_previous(self):
        writes, state, error = self.run_promotion([RuntimeError("unhealthy"), None])
        self.assertEqual(len(writes), 2)
        self.assertEqual(state["forward_host"], "previous")
        self.assertIn("previous upstream restored", error)

    def test_uncertain_update_is_rolled_back(self):
        writes, state, error = self.run_promotion([None], fail_first_write=True)
        self.assertEqual(len(writes), 2)
        self.assertEqual(state["forward_host"], "previous")
        self.assertIn("previous upstream restored", error)

    def test_failed_rollback_requires_manual_attention(self):
        _, _, error = self.run_promotion([RuntimeError("unhealthy")], fail_rollback=True)
        self.assertIn("ROLLBACK UNCONFIRMED", error)


class DiscoveryTests(unittest.TestCase):
    def test_missing_or_ambiguous_host_rejected_before_mutation(self):
        env = {"NPM_URL": "https://npm.example", "NPM_USERNAME": "user", "NPM_PASSWORD": "secret", "SERVICE_DOMAIN": "dev.example"}
        for hosts in ([], [{"id": 1, "domain_names": ["dev.example"]}] * 2):
            with self.subTest(hosts=hosts), patch.dict(os.environ, env), \
                 patch.object(deploy, "request", side_effect=[{"token": "token"}, hosts]) as api:
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    deploy.connect()
                self.assertEqual(api.call_count, 2)


if __name__ == "__main__":
    unittest.main()
