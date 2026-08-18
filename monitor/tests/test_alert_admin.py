import json
from unittest.mock import patch

from django.contrib import admin
from django.test import TestCase

from monitor.admin import AlertAdmin, EstimatedCountPaginator
from monitor.models import Alert


class EstimatedCountPaginatorTests(TestCase):
    def test_uses_query_plan_row_estimate(self):
        queryset = Alert.objects.all()
        plan = json.dumps([{"Plan": {"Plan Rows": 26_000_000}}])

        with patch.object(queryset, "explain", return_value=plan):
            paginator = EstimatedCountPaginator(queryset, 100)
            self.assertEqual(paginator.count, 26_000_000)

    def test_alert_admin_is_configured_for_large_table(self):
        model_admin = AlertAdmin(Alert, admin.site)

        self.assertEqual(model_admin.ordering, ("-id",))
        self.assertIs(model_admin.paginator, EstimatedCountPaginator)
        self.assertFalse(model_admin.show_full_result_count)
        self.assertEqual(model_admin.show_facets, admin.ShowFacets.NEVER)
