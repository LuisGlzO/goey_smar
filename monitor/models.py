from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator


class ObservationSource(models.TextChoices):
    SCRAPER = "scraper", "Scraper"
    CREATORS_API = "creators_api", "Creators API"
    MANUAL = "manual", "Manual"


class ScraperAccount(models.Model):
    key = models.SlugField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ("key",)
        verbose_name = "Cuenta scraper de Amazon"
        verbose_name_plural = "Cuentas scraper de Amazon"

    def __str__(self):
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_key = instance.key
        return instance

    def save(self, *args, **kwargs):
        original_key = getattr(self, "_original_key", self.key)
        if not self._state.adding and self.key != original_key:
            raise ValueError("La clave de una cuenta scraper es inmutable.")
        super().save(*args, **kwargs)
        self._original_key = self.key


class ProductGroup(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=7,
        default="#11999E",
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="El color debe tener el formato hexadecimal #RRGGBB.",
            )
        ],
    )
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_order", "name", "pk")
        verbose_name = "Grupo de productos"
        verbose_name_plural = "Grupos de productos"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.color = self.color.upper()
        super().save(*args, **kwargs)


class Product(models.Model):
    class Priority(models.IntegerChoices):
        LOW = 10, "Baja"
        NORMAL = 20, "Normal"
        HIGH = 30, "Alta"

    asin = models.CharField(max_length=10, unique=True)
    scraper_account = models.ForeignKey(
        ScraperAccount, on_delete=models.PROTECT, related_name="products", default="amazon_a"
    )
    group = models.ForeignKey(
        ProductGroup,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    group_order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=250)
    observations = models.TextField(blank=True)
    affiliate_url = models.URLField(
        max_length=1000,
        blank=True,
        help_text="Opcional. Tiene prioridad sobre el tag global de afiliado.",
    )
    image_url = models.URLField(max_length=2000, blank=True)
    image_refreshed_at = models.DateTimeField(null=True, blank=True)
    max_price = models.DecimalField(max_digits=12, decimal_places=2)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.HIGH)
    is_active = models.BooleanField(default=True)
    intentionally_not_in_cart = models.BooleanField(
        default=False,
        help_text="Indica que el producto permanece solo en el sistema de forma intencional.",
    )
    cooldown_minutes = models.PositiveIntegerField(default=60)
    max_alerts_per_day = models.PositiveIntegerField(default=99)
    significant_price_drop_percent = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-priority", "name")
        indexes = [models.Index(fields=("group", "group_order"), name="product_group_order_idx")]

    def __str__(self):
        return f"{self.asin} - {self.name}"

    def save(self, *args, **kwargs):
        self.asin = self.asin.strip().upper()
        super().save(*args, **kwargs)


class MonitorSettings(models.Model):
    enabled = models.BooleanField(default=True)
    anti_false_restock_cooldown_minutes = models.PositiveIntegerField(
        "Cooldown anti-falso-restock (minutos)",
        default=0,
        help_text=(
            "Minutos para bloquear una nueva alerta del mismo producto despues "
            "de una alerta enviada. Use 0 para desactivar."
        ),
    )
    active_from = models.TimeField(
        null=True,
        blank=True,
        help_text="Hora local desde la que se permite monitorear. Vacio significa sin limite.",
    )
    active_until = models.TimeField(
        null=True,
        blank=True,
        help_text="Hora local hasta la que se permite monitorear. Vacio significa sin limite.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracion del monitor"
        verbose_name_plural = "Configuracion del monitor"

    def __str__(self):
        return "Configuracion del monitor"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings

    def is_active_at(self, current_time):
        if not self.enabled:
            return False
        if not self.active_from or not self.active_until:
            return True
        if self.active_from == self.active_until:
            return True
        if self.active_from < self.active_until:
            return self.active_from <= current_time < self.active_until
        return current_time >= self.active_from or current_time < self.active_until


class MonitorRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "En ejecución"
        SUCCESS = "success", "Exitoso"
        FAILED = "failed", "Fallido"
        SKIPPED = "skipped", "Omitido"

    started_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=20, choices=ObservationSource.choices, default=ObservationSource.SCRAPER)
    worker_key = models.CharField(max_length=100, default="scraper:default", db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    items_seen = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    performance = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=("started_at", "id"), name="run_date_id_idx")]


class ProductCheck(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        UNAVAILABLE = "unavailable", "No disponible"
        UNKNOWN = "unknown", "Desconocido"

    run = models.ForeignKey(MonitorRun, null=True, blank=True, on_delete=models.CASCADE, related_name="checks")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="checks")
    source = models.CharField(max_length=20, choices=ObservationSource.choices, default=ObservationSource.SCRAPER)
    requested_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="manual_product_checks"
    )
    checked_at = models.DateTimeField(auto_now_add=True)
    availability = models.CharField(max_length=12, choices=Availability.choices)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    move_to_cart_visible = models.BooleanField(default=False)
    unavailable_message_visible = models.BooleanField(default=False)
    product_url = models.URLField(max_length=1000, blank=True)
    raw_text = models.TextField(blank=True)

    class Meta:
        ordering = ("-checked_at",)
        indexes = [
            models.Index(fields=("checked_at", "id"), name="check_date_id_idx"),
            models.Index(fields=("product", "-checked_at")),
            models.Index(
                fields=("product", "source", "-checked_at"),
                name="check_prod_source_date_idx",
            ),
        ]


class CartSnapshotItem(models.Model):
    run = models.ForeignKey(MonitorRun, on_delete=models.CASCADE, related_name="cart_items")
    scraper_account = models.ForeignKey(
        ScraperAccount, on_delete=models.CASCADE, related_name="cart_snapshot_items"
    )
    asin = models.CharField(max_length=10)
    source = models.CharField(max_length=12)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    product_url = models.URLField(max_length=1000, blank=True)
    raw_text = models.TextField(blank=True)

    class Meta:
        ordering = ("scraper_account_id", "asin")
        constraints = [
            models.UniqueConstraint(fields=("run", "asin"), name="unique_cart_item_per_run")
        ]
        indexes = [models.Index(fields=("scraper_account", "asin"))]


class Alert(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Procesando"
        SENT = "sent", "Enviada"
        SKIPPED = "skipped", "Omitida"
        FAILED = "failed", "Fallida"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts")
    product_check = models.ForeignKey(ProductCheck, on_delete=models.CASCADE, related_name="alerts")
    source = models.CharField(max_length=20, choices=ObservationSource.choices, default=ObservationSource.SCRAPER)
    requested_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="requested_alerts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=Status.choices)
    reservation_expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=80)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("product", "-created_at")),
            models.Index(fields=("status", "created_at", "id"), name="alert_cleanup_idx"),
            models.Index(fields=("status", "-id"), name="alert_status_id_idx"),
            models.Index(fields=("source", "-id"), name="alert_source_id_idx"),
            models.Index(fields=("reason", "-id"), name="alert_reason_id_idx"),
            models.Index(
                fields=("product", "-created_at", "-id"),
                condition=Q(status="sent"),
                name="alert_sent_prod_date_idx",
            ),
            models.Index(
                fields=("product", "reservation_expires_at"),
                condition=Q(status="processing"),
                name="alert_processing_res_idx",
            ),
        ]
        permissions = [("send_manual_alert", "Puede enviar alertas manuales")]


class DiscoverySource(models.Model):
    class SourceType(models.TextChoices):
        AMAZON_TOP_100 = "amazon_top_100", "Amazon Top 100"
        AMAZON_NEWEST = "amazon_newest", "Amazon Newest"
        AMAZON_TRACKERS = "amazon_trackers", "Amazon Trackers"
        MERCADO_LIBRE_SELLER = "mercado_libre_seller", "Mercado Libre Seller"

    PRICE_DROP_SOURCE_TYPES = {SourceType.AMAZON_TOP_100, SourceType.MERCADO_LIBRE_SELLER}

    name = models.CharField(max_length=150)
    url = models.URLField(max_length=2000)
    source_type = models.CharField(max_length=30, choices=SourceType.choices)
    is_active = models.BooleanField(default=True)
    interval_minutes = models.PositiveIntegerField(default=30)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dispatch_reserved_at = models.DateTimeField(null=True, blank=True)
    price_drop_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    configuration = models.JSONField(default=dict, blank=True)
    baseline_established = models.BooleanField(default=False)
    baseline_established_at = models.DateTimeField(null=True, blank=True)
    last_run = models.ForeignKey(
        "DiscoveryRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_successful_run = models.ForeignKey(
        "DiscoveryRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    last_status = models.CharField(max_length=12, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("source_type", "name", "pk")
        verbose_name = "Fuente de descubrimiento"
        verbose_name_plural = "Fuentes de descubrimiento"

    def __str__(self):
        return f"{self.get_source_type_display()} - {self.name}"

    def clean(self):
        super().clean()
        from .amazon_discovery import AmazonDiscoveryConfigurationError, normalize_amazon_url
        from .mercado_libre_discovery import (
            MercadoLibreConfigurationError,
            normalize_mercado_libre_url,
        )

        if self.interval_minutes < 1:
            raise ValidationError({"interval_minutes": "El intervalo debe ser mayor que cero."})
        if self.interval_minutes > 43200:
            raise ValidationError({"interval_minutes": "El intervalo no puede superar 30 días."})
        if self.source_type in self.PRICE_DROP_SOURCE_TYPES and self.price_drop_percent is None:
            raise ValidationError({"price_drop_percent": "Este tipo de fuente requiere un porcentaje."})
        if not isinstance(self.configuration, dict):
            raise ValidationError({"configuration": "La configuración debe ser un objeto JSON."})
        unknown = set(self.configuration) - {"max_pages", "timeout_seconds"}
        if unknown:
            raise ValidationError({
                "configuration": f"Opciones no permitidas: {', '.join(sorted(unknown))}."
            })
        limits = {"max_pages": (1, 100), "timeout_seconds": (1, 60)}
        for key, (minimum, maximum) in limits.items():
            if key not in self.configuration:
                continue
            value = self.configuration[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationError({"configuration": f"{key} debe ser numérico."})
            if not minimum <= value <= maximum:
                raise ValidationError({
                    "configuration": f"{key} debe estar entre {minimum} y {maximum}."
                })
        try:
            if self.source_type == self.SourceType.MERCADO_LIBRE_SELLER:
                self.url = normalize_mercado_libre_url(self.url)
            elif self.source_type in {
                self.SourceType.AMAZON_TOP_100,
                self.SourceType.AMAZON_NEWEST,
                self.SourceType.AMAZON_TRACKERS,
            }:
                self.url = normalize_amazon_url(self.url)
            else:
                raise ValidationError({"source_type": "Tipo de fuente no soportado."})
        except (AmazonDiscoveryConfigurationError, MercadoLibreConfigurationError) as exc:
            raise ValidationError({"url": str(exc)}) from exc

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)


class DiscoveryRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        RUNNING = "running", "Ejecutándose"
        SUCCESS = "success", "Exitosa"
        INCOMPLETE = "incomplete", "Incompleta"
        FAILED = "failed", "Fallida"
        SKIPPED = "skipped", "Omitida"

    source = models.ForeignKey(DiscoverySource, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    pages_found = models.PositiveIntegerField(default=0)
    products_found = models.PositiveIntegerField(default=0)
    known_products = models.PositiveIntegerField(default=0)
    new_products = models.PositiveIntegerField(default=0)
    exits = models.PositiveIntegerField(default=0)
    reentries = models.PositiveIntegerField(default=0)
    price_drops = models.PositiveIntegerField(default=0)
    events_created = models.PositiveIntegerField(default=0)
    notifications_created = models.PositiveIntegerField(default=0)
    is_diagnostic = models.BooleanField(
        default=False,
        help_text="La revisión solo inspeccionó la fuente; no modificó baseline, productos ni eventos.",
    )
    issues = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("-started_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("source",),
                condition=Q(status="running"),
                name="unique_running_discovery_source",
            )
        ]
        indexes = [
            models.Index(fields=("source", "-started_at"), name="discovery_run_source_idx"),
            models.Index(fields=("status", "-started_at"), name="discovery_run_status_idx"),
        ]

    def __str__(self):
        return f"{self.source} - {self.get_status_display()} - {self.started_at:%Y-%m-%d %H:%M}"


class DiscoveryProduct(models.Model):
    source = models.ForeignKey(DiscoverySource, on_delete=models.CASCADE, related_name="products")
    external_id = models.CharField(max_length=120)
    name = models.CharField(max_length=500)
    url = models.URLField(max_length=2000, blank=True)
    current_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notification_reference_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    is_present = models.BooleanField(default=True)
    position = models.PositiveIntegerField(null=True, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    last_entered_at = models.DateTimeField()
    last_exited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("source", "external_id")
        constraints = [
            models.UniqueConstraint(
                fields=("source", "external_id"), name="unique_discovery_product_source"
            )
        ]
        indexes = [
            models.Index(fields=("source", "is_present"), name="discovery_present_idx"),
            models.Index(fields=("source", "-last_seen_at"), name="discovery_last_seen_idx"),
        ]

    def __str__(self):
        return f"{self.external_id} - {self.name}"

    def save(self, *args, **kwargs):
        self.external_id = self.external_id.strip().upper()
        self.name = self.name.strip()
        super().save(*args, **kwargs)


class DiscoveryEvent(models.Model):
    class EventType(models.TextChoices):
        BASELINE = "baseline", "Baseline"
        NEW = "new", "Producto nuevo"
        EXIT = "exit", "Salida"
        REENTRY = "reentry", "Reingreso"
        PRICE_DROP = "price_drop", "Reducción de precio"

    run = models.ForeignKey(DiscoveryRun, on_delete=models.CASCADE, related_name="events")
    product = models.ForeignKey(DiscoveryProduct, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=12, choices=EventType.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    previous_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    new_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    previous_position = models.PositiveIntegerField(null=True, blank=True)
    new_position = models.PositiveIntegerField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("run", "product", "event_type"), name="unique_discovery_event_per_run"
            )
        ]
        indexes = [
            models.Index(fields=("event_type", "-created_at"), name="discovery_event_type_idx"),
            models.Index(fields=("run", "-created_at"), name="discovery_event_run_idx"),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.product}"


class DiscoveryNotification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PROCESSING = "processing", "Procesando"
        SENT = "sent", "Enviada"
        FAILED = "failed", "Fallida"

    event = models.OneToOneField(
        DiscoveryEvent, on_delete=models.CASCADE, related_name="notification"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivery_started_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    telegram_message_id = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("status", "-created_at"), name="discovery_notif_status_idx"),
        ]

    def __str__(self):
        return f"{self.event} - {self.get_status_display()}"
