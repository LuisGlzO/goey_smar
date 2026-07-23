from django.db import models


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


class Product(models.Model):
    class Priority(models.IntegerChoices):
        LOW = 10, "Baja"
        NORMAL = 20, "Normal"
        HIGH = 30, "Alta"

    asin = models.CharField(max_length=10, unique=True)
    scraper_account = models.ForeignKey(
        ScraperAccount, on_delete=models.PROTECT, related_name="products", default="amazon_a"
    )
    name = models.CharField(max_length=250)
    affiliate_url = models.URLField(
        max_length=1000,
        blank=True,
        help_text="Opcional. Tiene prioridad sobre el tag global de afiliado.",
    )
    image_url = models.URLField(max_length=2000, blank=True)
    image_refreshed_at = models.DateTimeField(null=True, blank=True)
    max_price = models.DecimalField(max_digits=12, decimal_places=2)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.NORMAL)
    is_active = models.BooleanField(default=True)
    cooldown_minutes = models.PositiveIntegerField(default=60)
    max_alerts_per_day = models.PositiveIntegerField(default=3)
    significant_price_drop_percent = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-priority", "name")

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
        indexes = [models.Index(fields=("product", "-checked_at"))]


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
        indexes = [models.Index(fields=("product", "-created_at"))]
        permissions = [("send_manual_alert", "Puede enviar alertas manuales")]
