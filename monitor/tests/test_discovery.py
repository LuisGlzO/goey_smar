from decimal import Decimal

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from monitor.admin import (
    DiscoveryEventAdmin,
    DiscoveryNotificationAdmin,
    DiscoveryProductAdmin,
    DiscoveryRunAdmin,
    DiscoverySourceAdmin,
)
from monitor.discovery import (
    DiscoveryHistoryItem,
    DiscoveryItem,
    compare_discovery_review,
    normalize_discovery_items,
    process_discovery_review,
)
from monitor.models import (
    Alert,
    DiscoveryEvent,
    DiscoveryNotification,
    DiscoveryProduct,
    DiscoveryRun,
    DiscoverySource,
    MonitorRun,
    Product,
    ProductCheck,
)


class DiscoveryModelTests(TestCase):
    def make_source(self, **kwargs):
        values = {
            "name": "Figuras",
            "url": "https://www.amazon.com.mx/bestsellers/toys",
            "source_type": DiscoverySource.SourceType.AMAZON_TOP_100,
            "price_drop_percent": Decimal("5.00"),
        }
        values.update(kwargs)
        return DiscoverySource.objects.create(**values)

    def test_source_choices_and_price_drop_validation(self):
        self.assertEqual(len(DiscoverySource.SourceType.choices), 4)
        source = DiscoverySource(
            name="Top", url="https://example.com/top", source_type=DiscoverySource.SourceType.AMAZON_TOP_100
        )
        with self.assertRaises(ValidationError):
            source.full_clean()
        source.price_drop_percent = Decimal("101")
        with self.assertRaises(ValidationError):
            source.full_clean()

    def test_source_rejects_unsafe_url_and_unbounded_configuration(self):
        source = DiscoverySource(
            name="Interna", url="http://127.0.0.1/admin",
            source_type=DiscoverySource.SourceType.AMAZON_TRACKERS,
        )
        with self.assertRaises(ValidationError) as caught:
            source.full_clean()
        self.assertIn("url", caught.exception.message_dict)
        source.url = "https://www.amazon.com.mx/s?k=seguro"
        source.configuration = {"max_pages": 1000}
        with self.assertRaises(ValidationError) as caught:
            source.full_clean()
        self.assertIn("configuration", caught.exception.message_dict)

    def test_product_is_unique_inside_source_but_not_across_sources(self):
        first_source = self.make_source()
        second_source = self.make_source(name="Otra")
        values = dict(
            external_id="ABC", name="Producto", first_seen_at="2026-01-01T00:00Z",
            last_seen_at="2026-01-01T00:00Z", last_entered_at="2026-01-01T00:00Z",
        )
        DiscoveryProduct.objects.create(source=first_source, **values)
        DiscoveryProduct.objects.create(source=second_source, **values)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DiscoveryProduct.objects.create(source=first_source, **values)

    def test_external_identifier_is_normalized(self):
        item = normalize_discovery_items([{"external_id": "  mlm-123 ", "name": " Artículo "}])[0]
        self.assertEqual(item.external_id, "MLM-123")
        self.assertEqual(item.name, "Artículo")

    def test_duplicate_review_entries_are_consolidated_by_last_value(self):
        items = normalize_discovery_items([
            {"external_id": "abc", "name": "Anterior", "price": "100"},
            {"external_id": "ABC", "name": "Actual", "price": "90"},
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "Actual")
        self.assertEqual(items[0].price, Decimal("90"))


class DiscoveryComparisonTests(TestCase):
    def test_comparison_is_pure_and_detects_exact_threshold(self):
        history = (
            DiscoveryHistoryItem("ABC", True, Decimal("98"), Decimal("100"), 1),
        )
        items = (DiscoveryItem("ABC", "Producto", price=Decimal("95"), position=2),)
        result = compare_discovery_review(
            source_type=DiscoverySource.SourceType.AMAZON_TOP_100,
            baseline_established=True,
            price_drop_percent=Decimal("5"),
            history=history,
            items=items,
            is_complete=True,
        )
        self.assertEqual(result.price_drops, ("ABC",))
        self.assertEqual(history[0].reference_price, Decimal("100"))

    def test_newest_does_not_create_exits_or_reentries(self):
        history = (DiscoveryHistoryItem("ABC", False, None, None, None),)
        result = compare_discovery_review(
            source_type=DiscoverySource.SourceType.AMAZON_NEWEST,
            baseline_established=True,
            price_drop_percent=None,
            history=history,
            items=(DiscoveryItem("ABC", "Conocido"),),
            is_complete=True,
        )
        self.assertEqual(result.known, ("ABC",))
        self.assertFalse(result.exits)
        self.assertFalse(result.reentries)


class DiscoveryProcessingTests(TestCase):
    def make_source(self, source_type=DiscoverySource.SourceType.AMAZON_TOP_100, **kwargs):
        values = {
            "name": "Fuente",
            "url": "https://example.com/source",
            "source_type": source_type,
            "price_drop_percent": Decimal("5") if source_type in DiscoverySource.PRICE_DROP_SOURCE_TYPES else None,
        }
        values.update(kwargs)
        return DiscoverySource.objects.create(**values)

    def review(self, source, products, **kwargs):
        return process_discovery_review(source, products, pages_found=kwargs.pop("pages_found", 1), **kwargs)

    def test_complete_first_review_creates_silent_baseline(self):
        source = self.make_source()
        run = self.review(source, [
            {"external_id": "A1", "name": "Uno", "price": "100", "position": 1},
            {"external_id": "A2", "name": "Dos", "price": "200", "position": 2},
        ], pages_found=3)
        source.refresh_from_db()
        self.assertEqual(run.status, DiscoveryRun.Status.SUCCESS)
        self.assertEqual((run.pages_found, run.products_found, run.events_created), (3, 2, 2))
        self.assertEqual(run.notifications_created, 0)
        self.assertTrue(source.baseline_established)
        self.assertEqual(DiscoveryEvent.objects.filter(event_type="baseline").count(), 2)
        self.assertFalse(DiscoveryNotification.objects.exists())

    def test_incomplete_first_review_is_silent_and_does_not_establish_baseline(self):
        source = self.make_source()
        run = self.review(
            source, [{"external_id": "A1", "name": "Uno", "price": "100"}], is_complete=False
        )
        source.refresh_from_db()
        self.assertEqual(run.status, DiscoveryRun.Status.INCOMPLETE)
        self.assertFalse(source.baseline_established)
        self.assertTrue(DiscoveryProduct.objects.filter(source=source, external_id="A1").exists())
        self.assertFalse(DiscoveryEvent.objects.exists())

    def test_new_product_creates_event_and_pending_outbox(self):
        source = self.make_source()
        self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
        run = self.review(source, [
            {"external_id": "A1", "name": "Uno", "price": "100"},
            {"external_id": "A2", "name": "Dos", "price": "75"},
        ])
        event = run.events.get(event_type=DiscoveryEvent.EventType.NEW)
        self.assertEqual(event.product.external_id, "A2")
        self.assertEqual(event.notification.status, DiscoveryNotification.Status.PENDING)
        self.assertEqual(event.notification.payload["source_type"], source.source_type)
        self.assertEqual((run.new_products, run.notifications_created), (1, 1))

    def test_known_product_does_not_duplicate_events(self):
        source = self.make_source()
        self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
        run = self.review(source, [{"external_id": "A1", "name": "Uno", "price": "98"}])
        self.assertEqual(run.known_products, 1)
        self.assertEqual(run.events_created, 0)

    def test_complete_exit_and_reentry_are_persisted(self):
        for source_type in (
            DiscoverySource.SourceType.AMAZON_TOP_100,
            DiscoverySource.SourceType.MERCADO_LIBRE_SELLER,
        ):
            with self.subTest(source_type=source_type):
                source = self.make_source(source_type, name=source_type)
                self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
                exit_run = self.review(source, [])
                product = source.products.get()
                self.assertFalse(product.is_present)
                self.assertEqual(exit_run.events.get().event_type, DiscoveryEvent.EventType.EXIT)
                self.assertFalse(DiscoveryNotification.objects.filter(event__run=exit_run).exists())
                reentry_run = self.review(
                    source, [{"external_id": "A1", "name": "Uno", "price": "90"}]
                )
                product.refresh_from_db()
                self.assertTrue(product.is_present)
                self.assertEqual(reentry_run.reentries, 1)
                self.assertIn(
                    DiscoveryEvent.EventType.REENTRY,
                    reentry_run.events.values_list("event_type", flat=True),
                )
                notifications = DiscoveryNotification.objects.filter(event__run=reentry_run)
                if source_type == DiscoverySource.SourceType.MERCADO_LIBRE_SELLER:
                    self.assertEqual(reentry_run.price_drops, 1)
                    self.assertEqual(
                        set(notifications.values_list("event__event_type", flat=True)),
                        {DiscoveryEvent.EventType.PRICE_DROP},
                    )
                else:
                    self.assertTrue(notifications.exists())

    def test_mercado_libre_reentry_without_a_significant_drop_is_silent(self):
        source = self.make_source(DiscoverySource.SourceType.MERCADO_LIBRE_SELLER)
        self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
        self.review(source, [])
        reentry = self.review(source, [{"external_id": "A1", "name": "Uno", "price": "99"}])
        self.assertEqual((reentry.reentries, reentry.price_drops), (1, 0))
        self.assertFalse(DiscoveryNotification.objects.filter(event__run=reentry).exists())

    def test_incomplete_review_does_not_mark_absent(self):
        source = self.make_source()
        self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
        run = self.review(source, [], is_complete=False)
        self.assertEqual(run.status, DiscoveryRun.Status.INCOMPLETE)
        self.assertTrue(source.products.get().is_present)
        self.assertFalse(run.events.exists())

    def test_newest_and_trackers_ignore_absence(self):
        for source_type in (
            DiscoverySource.SourceType.AMAZON_NEWEST,
            DiscoverySource.SourceType.AMAZON_TRACKERS,
        ):
            with self.subTest(source_type=source_type):
                source = self.make_source(source_type, name=source_type)
                self.review(source, [{"external_id": "A1", "name": "Uno"}])
                run = self.review(source, [])
                self.assertTrue(source.products.get().is_present)
                self.assertFalse(run.events.exists())

    def test_tracker_accepts_new_product_without_price(self):
        source = self.make_source(DiscoverySource.SourceType.AMAZON_TRACKERS)
        self.review(source, [])
        run = self.review(source, [{"external_id": "FUTURE", "name": "Preventa"}])
        self.assertEqual(run.new_products, 1)
        self.assertIsNone(source.products.get().current_price)
        self.assertEqual(run.notifications_created, 1)

    def test_price_drop_uses_and_updates_notification_reference(self):
        source = self.make_source()
        self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
        minor = self.review(source, [{"external_id": "A1", "name": "Uno", "price": "96"}])
        product = source.products.get()
        self.assertEqual(minor.price_drops, 0)
        self.assertEqual(product.current_price, Decimal("96"))
        self.assertEqual(product.notification_reference_price, Decimal("100"))
        drop = self.review(source, [{"external_id": "A1", "name": "Uno", "price": "95"}])
        product.refresh_from_db()
        self.assertEqual(drop.price_drops, 1)
        self.assertEqual(product.notification_reference_price, Decimal("95"))
        self.assertEqual(drop.events.get().previous_price, Decimal("100"))

    def test_inactive_and_overlapping_sources_are_skipped(self):
        inactive = self.make_source(is_active=False)
        skipped = self.review(inactive, [])
        self.assertEqual((skipped.status, skipped.error), ("skipped", "source_inactive"))

        source = self.make_source(name="Activa")
        DiscoveryRun.objects.create(source=source, status=DiscoveryRun.Status.RUNNING)
        overlap = self.review(source, [])
        self.assertEqual((overlap.status, overlap.error), ("skipped", "previous_run_still_running"))

    def test_source_can_run_after_previous_run_finishes(self):
        source = self.make_source()
        previous = DiscoveryRun.objects.create(source=source, status=DiscoveryRun.Status.RUNNING)
        previous.status = DiscoveryRun.Status.FAILED
        previous.save(update_fields=("status",))
        run = self.review(source, [])
        self.assertEqual(run.status, DiscoveryRun.Status.SUCCESS)

    def test_invalid_review_is_failed_without_partial_product_changes(self):
        source = self.make_source()
        with self.assertRaises(ValidationError):
            self.review(source, [
                {"external_id": "A1", "name": "Válido"},
                {"external_id": "", "name": "Inválido"},
            ])
        run = DiscoveryRun.objects.get(source=source)
        source.refresh_from_db()
        self.assertEqual(run.status, DiscoveryRun.Status.FAILED)
        self.assertIn("identificador externo", run.error)
        self.assertEqual(source.last_status, DiscoveryRun.Status.FAILED)
        self.assertFalse(source.products.exists())

    def test_invalid_review_metadata_is_also_audited_as_failed(self):
        source = self.make_source()
        with self.assertRaises(ValidationError):
            process_discovery_review(source, [], pages_found=-1)
        self.assertEqual(source.runs.get().status, DiscoveryRun.Status.FAILED)

    def test_errors_and_history_are_isolated_per_source(self):
        failed_source = self.make_source(name="Fallida")
        good_source = self.make_source(name="Correcta")
        with self.assertRaises(ValidationError):
            self.review(failed_source, [{"external_id": "BAD", "name": ""}])
        good_run = self.review(good_source, [{"external_id": "OK", "name": "Correcto"}])
        self.assertEqual(good_run.status, DiscoveryRun.Status.SUCCESS)
        self.assertEqual(good_source.products.count(), 1)
        self.assertFalse(failed_source.products.exists())

    def test_end_to_end_fake_reviews_never_touch_commercial_models(self):
        source = self.make_source()
        self.review(source, [{"external_id": "A1", "name": "Uno", "price": "100"}])
        second = self.review(source, [
            {"external_id": "A1", "name": "Uno", "price": "90"},
            {"external_id": "A2", "name": "Dos", "price": "50"},
        ])
        self.assertEqual(set(second.events.values_list("event_type", flat=True)), {"new", "price_drop"})
        self.assertEqual(second.notifications_created, 2)
        self.assertEqual((Product.objects.count(), ProductCheck.objects.count(), Alert.objects.count()), (0, 0, 0))
        self.assertEqual(MonitorRun.objects.count(), 0)


class DiscoveryAdminTests(TestCase):
    def test_all_discovery_models_are_registered_with_read_only_histories(self):
        self.assertIsInstance(admin.site._registry[DiscoverySource], DiscoverySourceAdmin)
        for model, model_admin in (
            (DiscoveryProduct, DiscoveryProductAdmin),
            (DiscoveryRun, DiscoveryRunAdmin),
            (DiscoveryEvent, DiscoveryEventAdmin),
            (DiscoveryNotification, DiscoveryNotificationAdmin),
        ):
            registered = admin.site._registry[model]
            self.assertIsInstance(registered, model_admin)
            self.assertFalse(registered.has_add_permission(None))
            self.assertFalse(registered.has_delete_permission(None))
