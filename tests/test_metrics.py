from unittest.mock import MagicMock, patch
import sys

# Standard way to mock missing libraries in environments where they are not installed
# and still avoid the risks of direct sys.modules manipulation in the main test logic.
mock_psutil = MagicMock()
mock_prometheus = MagicMock()

# Ensure Gauge returns unique mocks for each instance
mock_prometheus.Gauge.side_effect = lambda *args, **kwargs: MagicMock()

with patch.dict(sys.modules, {"psutil": mock_psutil, "prometheus_client": mock_prometheus}):
    from local_ai_brain.metrics import (
        process_memory_used_bytes,
        system_memory_used_bytes,
        update_memory_metrics,
    )

def test_update_memory_metrics():
    # Setup mock data
    mock_rss = 12345678
    mock_system_used = 87654321

    # Configure psutil.Process().memory_info().rss
    mock_process_instance = MagicMock()
    mock_process_instance.memory_info.return_value.rss = mock_rss
    mock_psutil.Process.return_value = mock_process_instance

    # Configure psutil.virtual_memory().used
    mock_vm = MagicMock()
    mock_vm.used = mock_system_used
    mock_psutil.virtual_memory.return_value = mock_vm

    # Call the function
    update_memory_metrics()

    # Verify psutil was called correctly
    mock_psutil.Process.assert_called_once()
    mock_psutil.virtual_memory.assert_called_once()

    # Verify gauges were updated with correct values
    process_memory_used_bytes.set.assert_called_once_with(mock_rss)
    system_memory_used_bytes.set.assert_called_once_with(mock_system_used)
