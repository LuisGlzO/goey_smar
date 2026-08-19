from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from monitor.models import Alert, CartSnapshotItem, MonitorRun, ProductCheck


PRESERVED_ALERT_STATUSES = (
    Alert.Status.SENT,
    Alert.Status.FAILED,
    Alert.Status.PROCESSING,
)


def delete_in_batches(queryset, batch_size, *, order_by=("pk",), progress_callback=None):
    deleted = 0
    while True:
        ids = list(queryset.order_by(*order_by).values_list("pk", flat=True)[:batch_size])
        if not ids:
            return deleted
        with transaction.atomic():
            queryset.model.objects.filter(pk__in=ids).delete()
        deleted += len(ids)
        if progress_callback and deleted % (batch_size * 100) == 0:
            progress_callback(deleted)


class Command(BaseCommand):
    help = "Limpia historial operativo antiguo sin eliminar alertas SENT o FAILED."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.MONITOR_RETENTION_DAYS)
        parser.add_argument("--batch-size", type=int, default=settings.MONITOR_RETENTION_BATCH_SIZE)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = options["days"]
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        if days <= 0:
            raise CommandError("--days debe ser mayor que cero.")
        if batch_size <= 0:
            raise CommandError("--batch-size debe ser mayor que cero.")

        now = timezone.now()
        cutoff = now - timedelta(days=days)
        expired_processing = Alert.objects.filter(
            status=Alert.Status.PROCESSING,
            reservation_expires_at__lt=now,
        )
        old_skipped = Alert.objects.filter(
            status=Alert.Status.SKIPPED,
            created_at__lt=cutoff,
        )
        removable_checks = ProductCheck.objects.filter(
            checked_at__lt=cutoff,
        ).exclude(
            alerts__status__in=PRESERVED_ALERT_STATUSES,
        ).distinct()
        old_snapshots = CartSnapshotItem.objects.filter(run__started_at__lt=cutoff)
        removable_runs = MonitorRun.objects.filter(
            started_at__lt=cutoff,
        ).exclude(
            checks__alerts__status__in=PRESERVED_ALERT_STATUSES,
        ).distinct()

        self.stdout.write(f"cutoff={cutoff.isoformat()} days={days} batch_size={batch_size}")
        if dry_run:
            self.stdout.write("dry_run=true")
            self.stdout.write(f"expired_processing_to_failed={expired_processing.count()}")
            self.stdout.write(f"skipped_alerts_to_delete={old_skipped.count()}")
            self.stdout.write(f"product_checks_to_delete={removable_checks.count()}")
            self.stdout.write(f"cart_snapshots_to_delete={old_snapshots.count()}")
            self.stdout.write(f"monitor_runs_to_delete={removable_runs.count()}")
            return

        expired_count = expired_processing.update(
            status=Alert.Status.FAILED,
            reason="reservation_expired",
            details="La reserva de envio expiro durante la limpieza de historial.",
            reservation_expires_at=None,
        )
        def progress(label):
            return lambda deleted: self.stdout.write(f"cleanup_progress {label}={deleted}")

        skipped_count = delete_in_batches(
            old_skipped,
            batch_size,
            order_by=("created_at", "pk"),
            progress_callback=progress("skipped_alerts"),
        )
        check_count = delete_in_batches(
            ProductCheck.objects.filter(checked_at__lt=cutoff, alerts__isnull=True),
            batch_size,
            order_by=("checked_at", "pk"),
            progress_callback=progress("product_checks"),
        )
        snapshot_count = delete_in_batches(
            old_snapshots,
            batch_size,
            order_by=("run__started_at", "pk"),
            progress_callback=progress("cart_snapshots"),
        )
        run_count = delete_in_batches(
            MonitorRun.objects.filter(
                started_at__lt=cutoff,
                checks__isnull=True,
                cart_items__isnull=True,
            ),
            batch_size,
            order_by=("started_at", "pk"),
            progress_callback=progress("monitor_runs"),
        )

        self.stdout.write(self.style.SUCCESS(
            "cleanup_complete "
            f"expired_processing={expired_count} "
            f"skipped_alerts={skipped_count} "
            f"product_checks={check_count} "
            f"cart_snapshots={snapshot_count} "
            f"monitor_runs={run_count}"
        ))
