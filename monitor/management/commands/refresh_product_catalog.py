import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from monitor.amazon_creators import creators_api_is_configured, get_products_content
from monitor.models import Product


class Command(BaseCommand):
    help = "Actualiza diariamente nombres e imagenes del catalogo desde Creators API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=settings.AMAZON_CREATORS_API_BATCH_SIZE,
            help="ASIN por solicitud (Creators API admite como maximo 10).",
        )
        parser.add_argument(
            "--batch-delay",
            type=float,
            default=settings.AMAZON_CREATORS_API_BATCH_DELAY_SECONDS,
            help="Segundos de espera entre solicitudes.",
        )
        parser.add_argument(
            "--active-only",
            action="store_true",
            help="Actualiza unicamente productos activos.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Consulta Creators API y muestra el resultado sin guardar cambios.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        batch_delay = options["batch_delay"]
        if not 1 <= batch_size <= 10:
            raise CommandError("--batch-size debe estar entre 1 y 10.")
        if batch_delay < 0:
            raise CommandError("--batch-delay no puede ser negativo.")
        if not creators_api_is_configured():
            raise CommandError("Creators API no esta configurada.")

        products = Product.objects.order_by("pk")
        if options["active_only"]:
            products = products.filter(is_active=True)

        total = products.count()
        updated = 0
        unchanged = 0
        missing = 0
        failures = []

        self.stdout.write(
            f"catalog_refresh_start total={total} batch_size={batch_size} "
            f"dry_run={str(options['dry_run']).lower()}"
        )
        for offset in range(0, total, batch_size):
            batch = list(products[offset:offset + batch_size])
            try:
                content_by_asin = get_products_content([product.asin for product in batch])
            except Exception as exc:
                failures.append(f"offset={offset} error={exc}")
                self.stderr.write(self.style.ERROR(f"catalog_refresh_batch_failed {failures[-1]}"))
                continue

            now = timezone.now()
            changed_products = []
            for product in batch:
                content = content_by_asin.get(product.asin)
                if content is None:
                    missing += 1
                    continue

                changed = False
                title = content.title[: Product._meta.get_field("name").max_length]
                if title and product.name != title:
                    product.name = title
                    changed = True
                if content.image_url:
                    if product.image_url != content.image_url:
                        product.image_url = content.image_url
                        changed = True
                    product.image_refreshed_at = now
                    changed = True

                if changed:
                    product.updated_at = now
                    changed_products.append(product)
                    updated += 1
                else:
                    unchanged += 1

            if changed_products and not options["dry_run"]:
                Product.objects.bulk_update(
                    changed_products,
                    ("name", "image_url", "image_refreshed_at", "updated_at"),
                )

            if offset + batch_size < total and batch_delay:
                time.sleep(batch_delay)

        summary = (
            f"catalog_refresh_complete total={total} updated={updated} "
            f"unchanged={unchanged} missing={missing} failed_batches={len(failures)}"
        )
        if failures:
            raise CommandError(f"{summary}; {'; '.join(failures)}")
        self.stdout.write(self.style.SUCCESS(summary))
