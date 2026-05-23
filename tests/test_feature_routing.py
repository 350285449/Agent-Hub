import unittest
from agent_hub.models import HubRequest, HubResponse, FailoverEvent
from agent_hub.session_store import SessionStore
from pathlib import Path
import tempfile

class TestFeatureRouting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.temp_dir.name))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_normal_routing_records_active_model(self):
        req = HubRequest(session_id="test_1", messages=[], task="test", raw={})
        # Response with no failovers
        res = HubResponse(
            request_id="req_1",
            session_id="test_1",
            agent="coding_agent",
            provider="openai",
            model="gpt-4o",
            text="Hello",
            raw={}
        )
        self.store.record_turn(req, res)
        
        # Check if session_models was added to the response's raw data through the side-effect in record_turn
        models = res.raw.get("agent_hub", {}).get("session_models", [])
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0], {"agent": "coding_agent", "provider": "openai", "model": "gpt-4o", "failed": False})

    def test_failover_routing_records_failed_and_active_model(self):
        req = HubRequest(session_id="test_2", messages=[], task="test", raw={})
        failover = FailoverEvent(agent="broken_agent", provider="anthropic", model="claude-3", reason="error")
        res = HubResponse(
            request_id="req_2",
            session_id="test_2",
            agent="coding_agent",
            provider="openai",
            model="gpt-4o",
            text="Hello",
            failover=[failover],
            raw={}
        )
        self.store.record_turn(req, res)
        
        models = res.raw.get("agent_hub", {}).get("session_models", [])
        self.assertEqual(len(models), 2)
        self.assertTrue(any(m["failed"] for m in models))
        self.assertTrue(any(not m["failed"] for m in models))

    def test_default_to_native_dict_hides_routing_details(self):
        res = HubResponse(
            request_id="req_3",
            session_id="test_3",
            agent="coding_agent",
            provider="openai",
            model="gpt-4o",
            text="Hello",
            raw={"agent_hub": {"session_models": [{"model": "secret"}]}}
        )
        
        # Default call
        native = res.to_native_dict()
        self.assertNotIn("agent_hub", native)
        self.assertNotIn("agent", native)
        
        # Specifically requested
        native_detailed = res.to_native_dict(include_routing_details=True)
        self.assertIn("agent_hub", native_detailed)
        self.assertEqual(native_detailed["agent_hub"]["session_models"][0]["model"], "secret")

if __name__ == "__main__":
    unittest.main()