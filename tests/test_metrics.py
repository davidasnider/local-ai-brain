import sys
from unittest.mock import MagicMock, patch

# This test is designed to be extremely isolated to avoid interference with other tests
# and to pass even in environments where hardware-specific dependencies (psutil)
# or monitoring libraries (prometheus_client) are not installed.


def test_update_memory_metrics():
    """
    Test that update_memory_metrics correctly retrieves memory info from psutil
    and updates the corresponding Prometheus gauges.
    """
    # Create isolated mocks for the dependencies
    mock_psutil = MagicMock()
    mock_prometheus = MagicMock()
    # Ensure each Gauge created returns a unique MagicMock
    # so we can track .set() calls independently
    mock_prometheus.Gauge.side_effect = lambda *args, **kwargs: MagicMock()

    # Use patch.dict to temporarily redirect imports of these libraries to our mocks.
    # This is necessary to avoid ImportError if metrics.py is imported for the first time here.
    with patch.dict(sys.modules, {"psutil": mock_psutil, "prometheus_client": mock_prometheus}):
        # We need to import metrics here so we can patch its internal references
        import local_ai_brain.metrics

        # Now we patch the specific references within the metrics module to ensure
        # that even if the module was already imported by another test, we are
        # using fresh, isolated mocks for THIS test.
        with (
            patch.object(local_ai_brain.metrics, "psutil", mock_psutil),
            patch.object(local_ai_brain.metrics, "process_memory_used_bytes") as mock_process_gauge,
            patch.object(local_ai_brain.metrics, "system_memory_used_bytes") as mock_system_gauge,
        ):
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

            # Call the function under test
            local_ai_brain.metrics.update_memory_metrics()

            # Verify psutil was called correctly
            mock_psutil.Process.assert_called_once()
            mock_psutil.virtual_memory.assert_called_once()

            # Verify the Prometheus gauges were updated with the expected values
            mock_process_gauge.set.assert_called_once_with(mock_rss)
            mock_system_gauge.set.assert_called_once_with(mock_system_used)
