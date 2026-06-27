from django.contrib import admin

from .models import Alert, MonitorRun, MonitorSettings, Product, ProductCheck


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("asin", "name", "max_price", "priority", "is_active", "cooldown_minutes", "max_alerts_per_day")
    list_filter = ("is_active", "priority")
    search_fields = ("asin", "name")


@admin.register(ProductCheck)
class ProductCheckAdmin(admin.ModelAdmin):
    list_display = ("checked_at", "product", "availability", "price", "move_to_cart_visible")
    list_filter = ("availability", "move_to_cart_visible", "unavailable_message_visible")
    search_fields = ("product__asin", "product__name")
    readonly_fields = ("run", "product", "checked_at", "availability", "price", "move_to_cart_visible", "unavailable_message_visible", "product_url", "raw_text")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "status", "reason")
    list_filter = ("status", "reason")
    readonly_fields = ("product", "product_check", "created_at", "status", "reason", "details")


@admin.register(MonitorRun)
class MonitorRunAdmin(admin.ModelAdmin):
    list_display = ("started_at", "finished_at", "status", "items_seen")
    list_filter = ("status",)
    readonly_fields = ("started_at", "finished_at", "status", "items_seen", "error")


@admin.register(MonitorSettings)
class MonitorSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "active_from", "active_until", "updated_at")
    fields = ("enabled", "active_from", "active_until", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not MonitorSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
