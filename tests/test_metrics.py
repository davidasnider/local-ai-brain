import importlib
import sys
from unittest.mock import MagicMock, patch

from opentelemetry.metrics import Observation


def test_otel_memory_callbacks():
    """
    Test that the memory callbacks correctly retrieve memory info from psutil.
    """
    # Setup mock data
    mock_rss = 12345678
    mock_system_used = 87654321

    # Patch psutil functions directly where they are used in local_ai_brain.metrics
    with (
        patch("psutil.Process") as mock_process_class,
        patch("psutil.virtual_memory") as mock_vm_func,
    ):
        # Configure mock process
        mock_process_instance = MagicMock()
        mock_process_instance.memory_info.return_value.rss = mock_rss
        mock_process_class.return_value = mock_process_instance

        # Configure mock virtual memory
        mock_vm_instance = MagicMock()
        mock_vm_instance.used = mock_system_used
        mock_vm_func.return_value = mock_vm_instance

        # Import metrics (ensuring it uses the patched psutil)
        if "local_ai_brain.metrics" in sys.modules:
            importlib.reload(sys.modules["local_ai_brain.metrics"])
        import local_ai_brain.metrics

        # Test get_process_memory callback
        process_observations = local_ai_brain.metrics.get_process_memory(None)

        # Verify psutil was called and values match
        mock_process_class.assert_called_once()
        assert len(process_observations) == 1
        assert isinstance(process_observations[0], Observation)
        assert process_observations[0].value == mock_rss

        # Test get_system_memory callback
        system_observations = local_ai_brain.metrics.get_system_memory(None)
        mock_vm_func.assert_called_once()
        assert len(system_observations) == 1
        assert isinstance(system_observations[0], Observation)
        assert system_observations[0].value == mock_system_used

    # Cleanup: remove from sys.modules to avoid polluting other tests
    if "local_ai_brain.metrics" in sys.modules:
        del sys.modules["local_ai_brain.metrics"]


def test_update_memory_metrics_is_noop():
    import local_ai_brain.metrics

    local_ai_brain.metrics.update_memory_metrics()

    # Cleanup
    if "local_ai_brain.metrics" in sys.modules:
        del sys.modules["local_ai_brain.metrics"]
