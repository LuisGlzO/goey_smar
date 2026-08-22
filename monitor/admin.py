import json

from django.contrib import admin
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils.functional import cached_property

from .models import (
    Alert,
    CartSnapshotItem,
    DiscoveryEvent,
    DiscoveryNotification,
    DiscoveryProduct,
    DiscoveryRun,
    DiscoverySource,
    MonitorRun,
    MonitorSettings,
    Product,
    ProductCheck,
    ProductGroup,
    ScraperAccount,
)


class EstimatedCountPaginator(Paginator):
    """Use the database planner estimate instead of COUNT(*) on large tables."""

    @cached_property
    def count(self):
        try:
            explanation = self.object_list.explain(format="json")
            if isinstance(explanation, str):
                explanation = json.loads(explanation)
            return max(int(explanation[0]["Plan"]["Plan Rows"]), 1)
        except (AttributeError, KeyError, TypeError, ValueError, NotImplementedError):
            return super().count


@admin.register(ScraperAccount)
class ScraperAccountAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "product_count")
    readonly_fields = ("key", "name")

    @admin.display(description="Productos")
    def product_count(self, obj):
        return obj.products.count()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("asin", "name", "group", "scraper_account", "max_price", "priority", "is_active", "cooldown_minutes", "max_alerts_per_day", "image_refreshed_at")
    readonly_fields = ("image_url", "image_refreshed_at")
    list_filter = ("group", "scraper_account", "is_active", "priority")
    search_fields = ("asin", "name", "observations")


@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "product_count", "updated_at")
    search_fields = ("name", "description")

    @admin.display(description="Productos")
    def product_count(self, obj):
        return obj.products.count()


@admin.register(ProductCheck)
class ProductCheckAdmin(admin.ModelAdmin):
    list_display = ("checked_at", "product", "source", "availability", "price", "move_to_cart_visible")
    list_filter = ("source", "availability", "move_to_cart_visible", "unavailable_message_visible")
    search_fields = ("product__asin", "product__name")
    readonly_fields = ("run", "product", "source", "requested_by", "checked_at", "availability", "price", "move_to_cart_visible", "unavailable_message_visible", "product_url", "raw_text")


@admin.register(CartSnapshotItem)
class CartSnapshotItemAdmin(admin.ModelAdmin):
    list_display = ("asin", "scraper_account", "source", "price", "run")
    list_filter = ("scraper_account", "source")
    search_fields = ("asin", "raw_text")
    readonly_fields = ("run", "scraper_account", "asin", "source", "price", "product_url", "raw_text")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "source", "status", "reason", "requested_by")
    list_filter = ("source", "status", "reason")
    readonly_fields = ("product", "product_check", "source", "requested_by", "created_at", "status", "reason", "details", "reservation_expires_at")
    ordering = ("-id",)
    paginator = EstimatedCountPaginator
    show_full_result_count = False
    show_facets = admin.ShowFacets.NEVER
    list_select_related = ("product", "requested_by")


@admin.register(MonitorRun)
class MonitorRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "source", "worker_key", "finished_at", "status", "items_seen", "duration_seconds")
    list_filter = ("source", "status")
    readonly_fields = ("source", "worker_key", "started_at", "finished_at", "status", "items_seen", "duration_seconds", "performance", "error")
    actions = ("mark_running_as_failed",)

    @admin.display(description="Duracion (s)")
    def duration_seconds(self, obj):
        if obj.finished_at:
            return round((obj.finished_at - obj.started_at).total_seconds(), 2)
        return ""

    @admin.action(description="Marcar ejecuciones en curso seleccionadas como fallidas")
    def mark_running_as_failed(self, request, queryset):
        from django.utils import timezone

        updated = queryset.filter(status=MonitorRun.Status.RUNNING).update(
            status=MonitorRun.Status.FAILED,
            finished_at=timezone.now(),
            error="manual_admin_recovery",
        )
        self.message_user(request, f"Ejecuciones marcadas como fallidas: {updated}.")


@admin.register(MonitorSettings)
class MonitorSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "anti_false_restock_cooldown_minutes", "active_from", "active_until", "updated_at")
    fields = ("enabled", "anti_false_restock_cooldown_minutes", "active_from", "active_until", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not MonitorSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DiscoverySource)
class DiscoverySourceAdmin(admin.ModelAdmin):
    list_display = (
        "name", "source_type", "is_active", "baseline_established", "last_status",
        "price_drop_percent", "interval_minutes", "last_run", "last_successful_run", "updated_at",
    )
    list_filter = ("source_type", "is_active", "baseline_established", "last_status")
    search_fields = ("name", "url")
    readonly_fields = (
        "baseline_established", "baseline_established_at", "last_run",
        "last_successful_run", "last_status", "created_at", "updated_at",
    )
    fields = (
        "name", "url", "source_type", "is_active", "price_drop_percent",
        "interval_minutes", "configuration", "next_run_at", "baseline_established",
        "baseline_established_at", "last_status", "last_run", "last_successful_run",
        "created_at", "updated_at",
    )
    actions = ("run_diagnostic", "activate_sources", "deactivate_sources")

    @admin.action(description="Ejecutar diagnóstico (no modifica el baseline)")
    def run_diagnostic(self, request, queryset):
        from django.conf import settings
        from .tasks import discovery_queue_for_source, run_discovery_source

        queued = 0
        for source in queryset:
            run_discovery_source.apply_async(
                args=(source.pk,), kwargs={"diagnostic": True},
                queue=discovery_queue_for_source(source),
                expires=settings.DISCOVERY_TASK_EXPIRES_SECONDS,
            )
            queued += 1
        self.message_user(
            request,
            f"Diagnósticos encolados: {queued}. No modificarán baseline, productos, eventos ni notificaciones.",
            messages.SUCCESS,
        )

    @admin.action(description="Activar fuentes seleccionadas")
    def activate_sources(self, request, queryset):
        self.message_user(request, f"Fuentes activadas: {queryset.update(is_active=True)}.")

    @admin.action(description="Desactivar fuentes seleccionadas")
    def deactivate_sources(self, request, queryset):
        self.message_user(request, f"Fuentes desactivadas: {queryset.update(is_active=False)}.")


@admin.register(DiscoveryProduct)
class DiscoveryProductAdmin(admin.ModelAdmin):
    list_display = (
        "external_id", "name", "source", "current_price", "is_present", "position", "last_seen_at",
    )
    list_filter = ("source__source_type", "is_present", "source")
    search_fields = ("external_id", "name", "source__name")
    readonly_fields = tuple(field.name for field in DiscoveryProduct._meta.fields)
    list_select_related = ("source",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(DiscoveryRun)
class DiscoveryRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at", "source", "status", "pages_found", "products_found",
        "is_diagnostic", "events_created", "notifications_created", "finished_at",
    )
    list_filter = ("status", "is_diagnostic", "source__source_type", "source")
    search_fields = ("source__name", "error")
    readonly_fields = tuple(field.name for field in DiscoveryRun._meta.fields)
    list_select_related = ("source",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(DiscoveryEvent)
class DiscoveryEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "product", "source_name", "run")
    list_filter = ("event_type", "run__source__source_type", "run__source")
    search_fields = ("product__external_id", "product__name", "run__source__name")
    readonly_fields = tuple(field.name for field in DiscoveryEvent._meta.fields)
    list_select_related = ("product", "run", "run__source")

    @admin.display(description="Fuente", ordering="run__source__name")
    def source_name(self, obj):
        return obj.run.source.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")


@admin.register(DiscoveryNotification)
class DiscoveryNotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "status", "event", "source_name", "sent_at", "failed_at")
    list_filter = ("status", "event__run__source__source_type", "event__run__source")
    search_fields = (
        "event__product__external_id", "event__product__name", "event__run__source__name",
    )
    readonly_fields = tuple(field.name for field in DiscoveryNotification._meta.fields)
    list_select_related = ("event", "event__product", "event__run", "event__run__source")

    @admin.display(description="Fuente", ordering="event__run__source__name")
    def source_name(self, obj):
        return obj.event.run.source.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")
