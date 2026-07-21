from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone


class MonitorSavedItemsCommandTests(SimpleTestCase):
    @patch("monitor.management.commands.monitor_saved_items.run_monitor")
    def test_prints_timings_with_equal_values_without_comparing_entries(self, run_monitor):
        started_at = timezone.now()
        run_monitor.return_value = type(
            "Run",
            (),
            {
                "pk": 199,
                "items_seen": 64,
                "started_at": started_at,
                "finished_at": started_at + timedelta(seconds=38.49),
                "status": "success",
                "performance": {
                    "stages": [
                        {"name": "first", "seconds": 0.004},
                        {"name": "second", "seconds": 0.004},
                    ]
                },
            },
        )()
        stdout = StringIO()

        call_command("monitor_saved_items", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("Ejecucion 199: 64 elementos visibles", output)
        self.assertIn("stages.first: 0.004s", output)
        self.assertIn("stages.second: 0.004s", output)
