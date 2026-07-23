from django.conf import settings
from django.test import SimpleTestCase

from config.celery import app


class CeleryRoutingTests(SimpleTestCase):
    def test_monitor_tasks_use_dedicated_queues(self):
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["monitor.tasks.monitor_saved_items"]["queue"],
            "scraper_amazon_a",
        )
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["monitor.tasks.monitor_creators_api"]["queue"],
            "creators_api",
        )

    def test_beat_entries_publish_to_dedicated_queues(self):
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-saved-items-amazon-a"]["options"]["queue"],
            "scraper_amazon_a",
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-saved-items-amazon-b"]["options"]["queue"],
            "scraper_amazon_b",
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-saved-items-amazon-b"]["options"]["countdown"],
            settings.MONITOR_INTERVAL_SECONDS // 2,
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-creators-api"]["options"]["queue"],
            "creators_api",
        )

    def test_celery_router_resolves_each_task_to_its_queue(self):
        self.assertEqual(
            app.amqp.router.route({}, "monitor.tasks.monitor_saved_items")["queue"].name,
            "scraper_amazon_a",
        )
        self.assertEqual(
            app.amqp.router.route({}, "monitor.tasks.monitor_creators_api")["queue"].name,
            "creators_api",
        )
