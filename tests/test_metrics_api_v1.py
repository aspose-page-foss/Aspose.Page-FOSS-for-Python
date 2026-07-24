from __future__ import annotations

import unittest
from argparse import Namespace
from tempfile import TemporaryDirectory
from pathlib import Path
import json
import os
from unittest.mock import patch

from tools.metrics_api_v1 import (
    build_headers,
    build_endpoint_url,
    build_payload,
    load_env_file,
    post_metrics,
    post_metrics_with_retries,
    resolve_api_key,
)


class TestMetricsApiV1(unittest.TestCase):
    def test_load_env_file_sets_missing_variables(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / ".env"
            path.write_text(
                "METRICS_API_KEY=env-key\nMETRICS_API_ENDPOINT=https://example.invalid/api\n",
                encoding="utf-8",
            )
            with patch.dict("os.environ", {}, clear=True):
                load_env_file(path)
                self.assertEqual(os.environ["METRICS_API_KEY"], "env-key")
                self.assertEqual(
                    os.environ["METRICS_API_ENDPOINT"], "https://example.invalid/api"
                )

    def test_resolve_api_key_raises_when_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                resolve_api_key()

    def test_resolve_api_key_prefers_explicit_value(self) -> None:
        with patch.dict("os.environ", {"METRICS_API_KEY": "env-key"}, clear=True):
            self.assertEqual(resolve_api_key("cli-key"), "cli-key")

    def test_build_endpoint_url_returns_endpoint_verbatim(self) -> None:
        endpoint = "https://metrics-api.aspose.app/agents"
        url = build_endpoint_url(endpoint)
        self.assertEqual(url, endpoint)

    def test_build_headers_uses_api_key_header(self) -> None:
        headers = build_headers("abc123")
        self.assertEqual(
            headers,
            {
                "Content-Type": "application/json",
                "X-Api-Key": "abc123",
            },
        )

    def test_build_payload_omits_empty_job_type(self) -> None:
        args = Namespace(
            payload_file=None,
            timestamp="2026-01-02T03:04:05.678Z",
            agent_name="agent",
            agent_owner="owner",
            job_type="",
            run_id="run-1",
            status="success",
            product="Aspose.Page",
            platform="Python",
            website="zap",
            website_section="Code Generation",
            item_name="item",
            items_discovered=10,
            items_failed=2,
            items_succeeded=8,
            run_duration_ms=123,
            token_usage=456,
            api_calls_count=7,
        )
        payload = build_payload(args)
        self.assertNotIn("job_type", payload)
        self.assertEqual(payload["run_id"], "run-1")

    def test_build_payload_includes_job_type_when_provided(self) -> None:
        args = Namespace(
            payload_file=None,
            timestamp="2026-01-02T03:04:05.678Z",
            agent_name="agent",
            agent_owner="owner",
            job_type="Debug tests",
            run_id="run-2",
            status="success",
            product="Aspose.Page",
            platform="Python",
            website="zap",
            website_section="Code Generation",
            item_name="item",
            items_discovered=10,
            items_failed=2,
            items_succeeded=8,
            run_duration_ms=123,
            token_usage=456,
            api_calls_count=7,
        )
        payload = build_payload(args)
        self.assertEqual(payload["job_type"], "Debug tests")

    def test_build_payload_from_file(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "payload.json"
            path.write_text(
                json.dumps(
                    {
                        "run_id": "from-file",
                        "status": "success",
                        "product": "Aspose.Page",
                        "platform": "Python",
                    }
                ),
                encoding="utf-8",
            )
            args = Namespace(
                payload_file=str(path),
                timestamp=None,
                agent_name=None,
                agent_owner=None,
                job_type=None,
                run_id=None,
                status=None,
                product=None,
                platform=None,
                website=None,
                website_section=None,
                item_name=None,
                items_discovered=None,
                items_failed=None,
                items_succeeded=None,
                run_duration_ms=None,
                token_usage=None,
                api_calls_count=None,
            )
            payload = build_payload(args)
            self.assertEqual(payload["run_id"], "from-file")

    def test_post_metrics_with_retries_eventual_success(self) -> None:
        calls = {"count": 0}

        def flaky_post(url, payload, api_key, timeout):
            calls["count"] += 1
            if calls["count"] < 3:
                raise OSError("temporary dns issue")
            self.assertEqual(api_key, "api-key")
            return 200, "ok"

        with patch("tools.metrics_api_v1.post_metrics", side_effect=flaky_post):
            status, body = post_metrics_with_retries(
                url="https://metrics-api.aspose.app/agents",
                payload={"run_id": "r1"},
                api_key="api-key",
                timeout=1.0,
                attempts=25,
                retry_delay_seconds=0.0,
            )
        self.assertEqual((status, body), (200, "ok"))
        self.assertEqual(calls["count"], 3)

    def test_post_metrics_with_retries_exhausted(self) -> None:
        with patch(
            "tools.metrics_api_v1.post_metrics",
            side_effect=OSError("network down"),
        ) as mocked_post:
            with self.assertRaises(OSError):
                post_metrics_with_retries(
                    url="https://metrics-api.aspose.app/agents",
                    payload={"run_id": "r2"},
                    api_key="api-key",
                    timeout=1.0,
                    attempts=4,
                    retry_delay_seconds=0.0,
                )
        self.assertEqual(mocked_post.call_count, 4)

    def test_post_metrics_uses_put_and_api_key(self) -> None:
        captured = {}

        class _Response:
            status = 202

            def read(self):
                return b"accepted"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_urlopen(request, timeout):
            captured["method"] = request.get_method()
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data.decode("utf-8")
            captured["timeout"] = timeout
            return _Response()

        with patch("tools.metrics_api_v1.urlopen", side_effect=fake_urlopen):
            status, body = post_metrics(
                url="https://metrics-api.aspose.app/agents",
                payload={"run_id": "r3", "status": "success"},
                api_key="secret-key",
                timeout=3.5,
            )

        self.assertEqual((status, body), (202, "accepted"))
        self.assertEqual(captured["method"], "PUT")
        self.assertEqual(captured["url"], "https://metrics-api.aspose.app/agents")
        self.assertEqual(captured["headers"]["Content-type"], "application/json")
        self.assertEqual(captured["headers"]["X-api-key"], "secret-key")
        self.assertIn('"run_id":"r3"', captured["body"])
        self.assertEqual(captured["timeout"], 3.5)


if __name__ == "__main__":
    unittest.main()
