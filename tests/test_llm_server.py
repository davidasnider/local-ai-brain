import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))


class TestLLMServer(unittest.TestCase):
    def test_patched_init_logic(self):
        # We test the patched_init function directly to verify its logic
        from local_ai_brain.models.llm_server import patched_init

        original_init = MagicMock()
        instance = MagicMock()

        with patch("local_ai_brain.models.llm_server.original_init", original_init):
            # Case 1: No prefill_step_size provided -> should set to 512
            patched_init(instance)
            args, kwargs = original_init.call_args
            self.assertEqual(kwargs["prefill_step_size"], 512)

            # Case 2: 2048 provided (default) -> should override to 512
            original_init.reset_mock()
            patched_init(instance, prefill_step_size=2048)
            args, kwargs = original_init.call_args
            self.assertEqual(kwargs["prefill_step_size"], 512)

            # Case 3: Custom value provided (e.g. 1024) -> should be preserved
            original_init.reset_mock()
            patched_init(instance, prefill_step_size=1024)
            args, kwargs = original_init.call_args
            self.assertEqual(kwargs["prefill_step_size"], 1024)

    def test_monkeypatch_presence(self):
        # Verify that the SimpleEngine.__init__ has indeed been replaced
        from vllm_mlx.engine.simple import SimpleEngine

        from local_ai_brain.models.llm_server import patched_init

        self.assertEqual(SimpleEngine.__init__, patched_init)


if __name__ == "__main__":
    unittest.main()
