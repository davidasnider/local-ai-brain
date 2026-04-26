import sys
from unittest.mock import MagicMock, patch

# Standard way to mock missing libraries in environments where they are not installed.
# We do this at the global level to ensure the module can be imported at all.
mock_psutil = MagicMock()
mock_prometheus = MagicMock()
mock_prometheus.Gauge.side_effect = lambda *args, **kwargs: MagicMock()

sys.modules["psutil"] = mock_psutil
sys.modules["prometheus_client"] = mock_prometheus

from local_ai_brain.metrics import update_memory_metrics


def test_update_memory_metrics():
    # Setup mock data
    mock_rss = 12345678
    mock_system_used = 87654321

    # We patch the attributes WITHIN local_ai_brain.metrics to be 100% sure we are
    # using fresh mocks for this test, even if the module was already imported.
    with patch("local_ai_brain.metrics.psutil") as patched_psutil, \
         patch("local_ai_brain.metrics.process_memory_used_bytes") as patched_process_gauge, \
         patch("local_ai_brain.metrics.system_memory_used_bytes") as patched_system_gauge:

        # Configure psutil.Process().memory_info().rss
        mock_process_instance = MagicMock()
        mock_process_instance.memory_info.return_value.rss = mock_rss
        patched_psutil.Process.return_value = mock_process_instance

        # Configure psutil.virtual_memory().used
        mock_vm = MagicMock()
        mock_vm.used = mock_system_used
        patched_psutil.virtual_memory.return_value = mock_vm

        # Call the function
        update_memory_metrics()

        # Verify psutil was called correctly
        patched_psutil.Process.assert_called_once()
        patched_psutil.virtual_memory.assert_called_once()

        # Verify gauges were updated with correct values
        patched_process_gauge.set.assert_called_once_with(mock_rss)
        patched_system_gauge.set.assert_called_once_with(mock_system_used)
