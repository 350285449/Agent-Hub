from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_hub.events import PROVIDER_SELECTED, RouterEventRecorder, request_source
from agent_hub.models import HubRequest
from agent_hub.observability import recent_events


class RouterEventRecorderTests(unittest.TestCase):
    def test_route_events_keep_existing_routing_stream_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            request = HubRequest(
                session_id="s",
                route="coding",
                preferred_agent="agent-a",
                api_shape="openai-chat",
                messages=[],
                metadata={"source": "cline"},
            )

            RouterEventRecorder(state_dir).route(
                "request_started",
                request_id="hub-1",
                request=request,
                routing_decision={"selected_agent": "agent-a"},
            )
            event = recent_events(state_dir, "routing")[-1]

            self.assertEqual(event["type"], "request_started")
            self.assertEqual(event["request_id"], "hub-1")
            self.assertEqual(event["session_id"], "s")
            self.assertEqual(event["route"], "coding")
            self.assertEqual(event["preferred_agent"], "agent-a")
            self.assertEqual(event["api_shape"], "openai-chat")
            self.assertEqual(event["source"], "cline")
            self.assertEqual(event["routing_decision"], {"selected_agent": "agent-a"})

    def test_internal_events_keep_request_context_and_sanitize_nested_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            request = HubRequest(
                session_id="s",
                route="coding",
                api_shape="native",
                messages=[],
                raw={"agent_hub": {"client": "agent-hub-test"}},
            )

            RouterEventRecorder(state_dir).internal(
                PROVIDER_SELECTED,
                request_id="hub-2",
                request=request,
                metadata={"api_key": "secret", "visible": "ok"},
            )
            event = recent_events(state_dir, "events")[-1]

            self.assertEqual(event["name"], PROVIDER_SELECTED)
            self.assertEqual(event["request_id"], "hub-2")
            self.assertEqual(event["session_id"], "s")
            self.assertEqual(event["source"], "agent-hub-test")
            self.assertEqual(event["metadata"], {"visible": "ok"})

    def test_request_source_priority_matches_router_compatibility_contract(self) -> None:
        request = HubRequest(
            session_id="s",
            api_shape="openai-chat",
            messages=[],
            raw={"source": "raw-source", "agent_hub": {"client": "hub-client"}},
            metadata={"client": "metadata-client"},
        )

        self.assertEqual(request_source(request), "metadata-client")
        self.assertEqual(
            request_source(HubRequest(session_id="s", api_shape="anthropic-messages", messages=[])),
            "anthropic-messages",
        )


if __name__ == "__main__":
    unittest.main()
