from __future__ import annotations

import json
import unittest

from agent_hub.api.compatibility import (
    anthropic_sse_frames,
    openai_chat_sse_frames,
    openai_response_sse_frames,
    sse_data_frame,
    sse_named_event_frame,
)
from agent_hub.models import HubResponse


class ApiCompatibilityPhaseNineTests(unittest.TestCase):
    def test_openai_chat_sse_frames_preserve_data_framing_and_done_marker(self) -> None:
        frames = openai_chat_sse_frames(_response("hello"))

        self.assertTrue(all(frame.endswith("\n\n") for frame in frames))
        self.assertTrue(frames[0].startswith("data: "))
        self.assertIn('"object": "chat.completion.chunk"', frames[0])
        self.assertEqual(frames[-1], "data: [DONE]\n\n")

    def test_anthropic_sse_frames_preserve_named_event_framing(self) -> None:
        frames = anthropic_sse_frames(_response("hello"))

        self.assertTrue(frames[0].startswith("event: message_start\n"))
        self.assertIn("data: ", frames[0])
        self.assertTrue(any(frame.startswith("event: content_block_delta\n") for frame in frames))
        self.assertTrue(frames[-1].startswith("event: message_stop\n"))

    def test_openai_response_sse_frames_preserve_response_event_framing(self) -> None:
        frames = openai_response_sse_frames(_response("hello"))

        self.assertTrue(frames[0].startswith("data: "))
        self.assertIn('"type": "response.created"', frames[0])
        self.assertTrue(any('"type": "response.completed"' in frame for frame in frames))
        self.assertEqual(frames[-1], "data: [DONE]\n\n")

    def test_low_level_sse_frame_helpers_format_json_and_named_events(self) -> None:
        data_frame = sse_data_frame({"type": "custom", "value": "ok"})
        event_frame = sse_named_event_frame("custom", {"value": "ok"})

        self.assertEqual(json.loads(data_frame.removeprefix("data: ").strip()), {"type": "custom", "value": "ok"})
        self.assertTrue(event_frame.startswith("event: custom\n"))
        self.assertEqual(json.loads(event_frame.split("data: ", 1)[1].strip()), {"value": "ok"})


def _response(text: str) -> HubResponse:
    return HubResponse(
        request_id="hub-1",
        session_id="s",
        agent="tooly",
        provider="echo",
        model="echo",
        public_model="agent-hub-coding",
        text=text,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    )


if __name__ == "__main__":
    unittest.main()
