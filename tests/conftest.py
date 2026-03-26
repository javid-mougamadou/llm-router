"""Pytest fixtures for llm-router tests."""

import os
import sys

# Add src to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Use temp DB for tests
os.environ["LLM_ROUTER_DB"] = "/tmp/test_llm_router.db"
os.environ["MASTER_KEY"] = "sk-test-master"
os.environ["ADMIN_USER"] = "testadmin"
os.environ["ADMIN_PASSWORD"] = "testpass"
