from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import codex_hook_post_metrics as hook


class TestCodexHookPostMetrics(unittest.TestCase):
    def test_hook_uses_new_metrics_endpoint_and_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "posted.json"
            log_path = Path(td) / "hook.log"

            payload_capture = {}

            def fake_post_metrics_with_retries(
                *,
                url,
                payload,
                api_key,
                timeout,
                attempts,
                retry_delay_seconds,
            ):
                payload_capture["url"] = url
                payload_capture["payload"] = payload
                payload_capture["api_key"] = api_key
                payload_capture["timeout"] = timeout
                payload_capture["attempts"] = attempts
                payload_capture["retry_delay_seconds"] = retry_delay_seconds
                return 200, "ok"

            hook_input = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "turn_id": "turn-1",
            }

            stdout = io.StringIO()
            with (
                patch.object(hook, "STATE_PATH", state_path),
                patch.object(hook, "HOOK_LOG_PATH", log_path),
                patch.object(hook, "_read_input", return_value=hook_input),
                patch.object(hook, "post_metrics_with_retries", side_effect=fake_post_metrics_with_retries),
                patch.dict(
                    "os.environ",
                    {
                        "METRICS_API_ENDPOINT": "https://metrics-api.aspose.app/agents",
                        "METRICS_API_KEY": "new-api-key",
                    },
                    clear=False,
                ),
                redirect_stdout(stdout),
            ):
                rc = hook.main()

        self.assertEqual(rc, 0)
        self.assertEqual(payload_capture["url"], "https://metrics-api.aspose.app/agents")
        self.assertEqual(payload_capture["api_key"], "new-api-key")
        self.assertEqual(payload_capture["payload"]["job_type"], "Auto post from Codex UserPromptSubmit hook")
        self.assertEqual(payload_capture["payload"]["status"], "in_progress")
        self.assertEqual(json.loads(stdout.getvalue()), {"continue": True})


if __name__ == "__main__":
    unittest.main()
