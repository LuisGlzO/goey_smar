from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.celery import app
from config.settings import _validate_distinct_periodic_phases, _validate_periodic_task_timing


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
            settings.CELERY_BEAT_SCHEDULE["monitor-saved-items-amazon-a"]["options"]["countdown"],
            settings.AMAZON_SCRAPER_A_COUNTDOWN_SECONDS,
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-saved-items-amazon-b"]["options"]["countdown"],
            settings.AMAZON_SCRAPER_B_COUNTDOWN_SECONDS,
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-creators-api"]["options"]["queue"],
            "creators_api",
        )
        self.assertEqual(
            settings.CELERY_BEAT_SCHEDULE["monitor-creators-api"]["options"]["countdown"],
            settings.AMAZON_CREATORS_API_COUNTDOWN_SECONDS,
        )

    def test_beat_entries_expire_after_their_eta_and_interval(self):
        entries = (
            ("monitor-saved-items-amazon-a", settings.AMAZON_SCRAPER_A_INTERVAL_SECONDS),
            ("monitor-saved-items-amazon-b", settings.AMAZON_SCRAPER_B_INTERVAL_SECONDS),
            ("monitor-creators-api", settings.AMAZON_CREATORS_API_INTERVAL_SECONDS),
        )
        for entry_name, interval in entries:
            options = settings.CELERY_BEAT_SCHEDULE[entry_name]["options"]
            self.assertEqual(options["expires"], interval + options["countdown"])

    def test_celery_router_resolves_each_task_to_its_queue(self):
        self.assertEqual(
            app.amqp.router.route({}, "monitor.tasks.monitor_saved_items")["queue"].name,
            "scraper_amazon_a",
        )
        self.assertEqual(
            app.amqp.router.route({}, "monitor.tasks.monitor_creators_api")["queue"].name,
            "creators_api",
        )

    def test_periodic_phase_validation_rejects_eventual_collisions(self):
        with self.assertRaises(ImproperlyConfigured):
            _validate_distinct_periodic_phases((
                ("A", 40, 0),
                ("B", 60, 20),
            ))

        _validate_distinct_periodic_phases((
            ("A", 40, 0),
            ("B", 40, 5),
            ("CREATORS", 40, 10),
        ))

    def test_periodic_timing_validation_rejects_invalid_values(self):
        for interval, countdown in ((0, 0), (40, -1), (40, 40), (40, 41)):
            with self.subTest(interval=interval, countdown=countdown):
                with self.assertRaises(ImproperlyConfigured):
                    _validate_periodic_task_timing("TEST", interval, countdown)
