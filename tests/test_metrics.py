import importlib
import sys
from unittest.mock import MagicMock, patch

# This test is designed to verify the OpenTelemetry observable gauge callbacks


def test_otel_memory_callbacks():
    """
    Test that the memory callbacks correctly retrieve memory info from psutil.
    """
    # Create isolated mocks for the dependencies
    mock_psutil = MagicMock()
    mock_metrics = MagicMock()

    # Use patch.dict to temporarily redirect imports of these libraries to our mocks.
    with patch.dict(sys.modules, {"psutil": mock_psutil, "opentelemetry": mock_metrics}):
        # Force a reload of the metrics module to use our mocks if it was already imported
        import local_ai_brain.metrics

        importlib.reload(local_ai_brain.metrics)

        # Setup mock data
        mock_rss = 12345678
        mock_system_used = 87654321

        # Configure the nested mock structure: psutil.Process().memory_info().rss
        mock_process_instance = MagicMock()
        mock_process_instance.memory_info.return_value.rss = mock_rss
        mock_psutil.Process.return_value = mock_process_instance

        # Configure the nested mock structure: psutil.virtual_memory().used
        mock_vm = MagicMock()
        mock_vm.used = mock_system_used
        mock_psutil.virtual_memory.return_value = mock_vm

        # Test get_process_memory callback
        process_observations = local_ai_brain.metrics.get_process_memory(MagicMock())

        # Verify psutil was called
        mock_psutil.Process.assert_called_once()
        assert len(process_observations) == 1

        # Test get_system_memory callback
        system_observations = local_ai_brain.metrics.get_system_memory(MagicMock())
        mock_psutil.virtual_memory.assert_called_once()
        assert len(system_observations) == 1


def test_update_memory_metrics_is_noop():
    import local_ai_brain.metrics

    # Should not raise any error
    local_ai_brain.metrics.update_memory_metrics()
