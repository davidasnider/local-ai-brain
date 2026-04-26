from unittest.mock import MagicMock, patch

from local_ai_brain.metrics import update_memory_metrics


def test_update_memory_metrics():
    mock_rss = 12345678
    mock_system_used = 87654321
    mock_pid = 42

    with (
        patch("local_ai_brain.metrics.psutil") as patched_psutil,
        patch("local_ai_brain.metrics.os.getpid", return_value=mock_pid),
        patch("local_ai_brain.metrics.process_memory_used_bytes") as patched_process_gauge,
        patch("local_ai_brain.metrics.system_memory_used_bytes") as patched_system_gauge,
    ):
        mock_process_instance = MagicMock()
        mock_process_instance.memory_info.return_value.rss = mock_rss
        patched_psutil.Process.return_value = mock_process_instance

        mock_vm = MagicMock()
        mock_vm.used = mock_system_used
        patched_psutil.virtual_memory.return_value = mock_vm

        update_memory_metrics()

        patched_psutil.Process.assert_called_once_with(mock_pid)
        patched_psutil.virtual_memory.assert_called_once()

        patched_process_gauge.set.assert_called_once_with(mock_rss)
        patched_system_gauge.set.assert_called_once_with(mock_system_used)
