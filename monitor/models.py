from django.db import models


class Product(models.Model):
    class Priority(models.IntegerChoices):
        LOW = 10, "Baja"
        NORMAL = 20, "Normal"
        HIGH = 30, "Alta"

    asin = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=250)
    affiliate_url = models.URLField(
        max_length=1000,
        blank=True,
        help_text="Opcional. Tiene prioridad sobre el tag global de afiliado.",
    )
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


class MonitorRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "En ejecución"
        SUCCESS = "success", "Exitoso"
        FAILED = "failed", "Fallido"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    items_seen = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)


class ProductCheck(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = "available", "Disponible"
        UNAVAILABLE = "unavailable", "No disponible"
        UNKNOWN = "unknown", "Desconocido"

    run = models.ForeignKey(MonitorRun, on_delete=models.CASCADE, related_name="checks")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="checks")
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
        SENT = "sent", "Enviada"
        SKIPPED = "skipped", "Omitida"
        FAILED = "failed", "Fallida"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts")
    product_check = models.ForeignKey(ProductCheck, on_delete=models.CASCADE, related_name="alerts")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=8, choices=Status.choices)
    reason = models.CharField(max_length=80)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("product", "-created_at"))]
