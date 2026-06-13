import unittest
import tempfile
import os
from pathlib import Path

from agent_hub.session_store import SessionStore
from agent_hub.models import HubRequest, HubResponse


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for the state
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name)
        self.store = SessionStore(self.state_dir)
    
    def tearDown(self):
        self.temp_dir.cleanup()
    
    def test_load_returns_default_for_nonexistent_session(self):
        """Loading a non-existent session returns the default structure."""
        result = self.store.load("nonexistent")
        self.assertEqual(result, {
            "session_id": "nonexistent",
            "messages": [],
            "events": []
        })

if __name__ == "__main__":
    unittest.main()
