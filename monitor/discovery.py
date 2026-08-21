from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    DiscoveryEvent,
    DiscoveryNotification,
    DiscoveryProduct,
    DiscoveryRun,
    DiscoverySource,
)


@dataclass(frozen=True)
class DiscoveryItem:
    external_id: str
    name: str
    url: str = ""
    price: Decimal | None = None
    position: int | None = None


@dataclass(frozen=True)
class DiscoveryHistoryItem:
    external_id: str
    is_present: bool
    current_price: Decimal | None
    reference_price: Decimal | None
    position: int | None


@dataclass(frozen=True)
class DiscoveryComparison:
    baseline: tuple[str, ...] = ()
    new: tuple[str, ...] = ()
    known: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()
    reentries: tuple[str, ...] = ()
    price_drops: tuple[str, ...] = ()


def normalize_discovery_items(items):
    """Validate and consolidate a review without touching the database."""
    normalized = {}
    validate_url = URLValidator()
    for raw in items:
        if isinstance(raw, DiscoveryItem):
            raw_external_id, raw_name = raw.external_id, raw.name
            raw_url, raw_price, raw_position = raw.url, raw.price, raw.position
        elif isinstance(raw, dict):
            raw_external_id = raw.get("external_id", "")
            raw_name = raw.get("name", "")
            raw_url = raw.get("url", "")
            raw_price = raw.get("price")
            raw_position = raw.get("position")
        else:
            raise ValidationError("Cada producto debe ser DiscoveryItem o un diccionario.")

        external_id = str(raw_external_id or "").strip().upper()
        name = str(raw_name or "").strip()
        url = str(raw_url or "").strip()
        if not external_id:
            raise ValidationError("El identificador externo es obligatorio.")
        if len(external_id) > 120:
            raise ValidationError(f"El identificador externo {external_id!r} excede 120 caracteres.")
        if not name:
            raise ValidationError(f"El nombre es obligatorio para {external_id}.")
        if len(name) > 500:
            raise ValidationError(f"El nombre de {external_id} excede 500 caracteres.")
        if url:
            validate_url(url)
        try:
            price = None if raw_price in (None, "") else Decimal(str(raw_price))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError(f"El precio de {external_id} no es válido.") from exc
        if price is not None and price < 0:
            raise ValidationError(f"El precio de {external_id} no puede ser negativo.")
        if raw_position in (None, ""):
            position = None
        else:
            try:
                position = int(raw_position)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"La posición de {external_id} no es válida.") from exc
            if position < 1:
                raise ValidationError(f"La posición de {external_id} debe ser mayor que cero.")
        normalized[external_id] = DiscoveryItem(external_id, name, url, price, position)
    return tuple(normalized.values())


def compare_discovery_review(
    *, source_type, baseline_established, price_drop_percent, history, items, is_complete
):
    """Compare a normalized review against immutable history, without side effects."""
    item_map = {item.external_id: item for item in items}
    history_map = {item.external_id: item for item in history}
    if not baseline_established:
        return DiscoveryComparison(
            baseline=tuple(item_map) if is_complete else (),
            known=tuple(item_map) if not is_complete else (),
        )

    supports_presence = source_type in DiscoverySource.PRICE_DROP_SOURCE_TYPES
    new, known, reentries, price_drops = [], [], [], []
    threshold = Decimal(str(price_drop_percent)) if price_drop_percent is not None else None
    for external_id, item in item_map.items():
        previous = history_map.get(external_id)
        if previous is None:
            new.append(external_id)
            continue
        known.append(external_id)
        if supports_presence and not previous.is_present:
            reentries.append(external_id)
            if source_type != DiscoverySource.SourceType.MERCADO_LIBRE_SELLER:
                continue
        if (
            supports_presence
            and threshold is not None
            and previous.reference_price is not None
            and previous.reference_price > 0
            and item.price is not None
        ):
            reduction = (previous.reference_price - item.price) * Decimal("100") / previous.reference_price
            if reduction >= threshold:
                price_drops.append(external_id)

    exits = ()
    if supports_presence and is_complete:
        exits = tuple(
            external_id
            for external_id, previous in history_map.items()
            if previous.is_present and external_id not in item_map
        )
    return DiscoveryComparison(
        new=tuple(new),
        known=tuple(known),
        exits=exits,
        reentries=tuple(reentries),
        price_drops=tuple(price_drops),
    )


def _start_discovery_run(source_id, *, allow_inactive=False):
    try:
        with transaction.atomic():
            source = DiscoverySource.objects.select_for_update().get(pk=source_id)
            if source.dispatch_reserved_at is not None:
                source.dispatch_reserved_at = None
                source.save(update_fields=("dispatch_reserved_at", "updated_at"))
            if not source.is_active and not allow_inactive:
                return DiscoveryRun.objects.create(
                    source=source,
                    status=DiscoveryRun.Status.SKIPPED,
                    finished_at=timezone.now(),
                    error="source_inactive",
                )
            if source.runs.filter(status=DiscoveryRun.Status.RUNNING).exists():
                return DiscoveryRun.objects.create(
                    source=source,
                    status=DiscoveryRun.Status.SKIPPED,
                    finished_at=timezone.now(),
                    error="previous_run_still_running",
                )
            return DiscoveryRun.objects.create(source=source, status=DiscoveryRun.Status.RUNNING)
    except IntegrityError:
        source = DiscoverySource.objects.get(pk=source_id)
        return DiscoveryRun.objects.create(
            source=source,
            status=DiscoveryRun.Status.SKIPPED,
            finished_at=timezone.now(),
            error="previous_run_still_running",
        )


def _event_payload(source, product, event_type, item):
    return {
        "source_id": source.pk,
        "source_type": source.source_type,
        "source_name": source.name,
        "event_type": event_type,
        "external_id": product.external_id,
        "name": product.name,
        "url": product.url,
        "price": str(item.price) if item and item.price is not None else None,
        "position": item.position if item else None,
    }


def _finish_failed_run(run, exc):
    now = timezone.now()
    error = str(exc) or exc.__class__.__name__
    DiscoveryRun.objects.filter(pk=run.pk).update(
        status=DiscoveryRun.Status.FAILED, finished_at=now, error=error
    )
    DiscoverySource.objects.filter(pk=run.source_id).update(
        last_run_id=run.pk, last_status=DiscoveryRun.Status.FAILED
    )


def process_discovery_review(source, items, *, pages_found=0, is_complete=True, run=None):
    """Persist one supplied review and return its independent DiscoveryRun."""
    source_id = source.pk if isinstance(source, DiscoverySource) else source
    run = run or _start_discovery_run(source_id)
    if run.status == DiscoveryRun.Status.SKIPPED:
        DiscoverySource.objects.filter(pk=source_id).update(
            last_run_id=run.pk, last_status=DiscoveryRun.Status.SKIPPED
        )
        return run

    try:
        if not isinstance(pages_found, int) or isinstance(pages_found, bool) or pages_found < 0:
            raise ValidationError("pages_found debe ser un entero no negativo.")
        if not isinstance(is_complete, bool):
            raise ValidationError("is_complete debe ser booleano.")
        normalized_items = normalize_discovery_items(items)
        with transaction.atomic():
            locked_source = DiscoverySource.objects.select_for_update().get(pk=source_id)
            products = list(
                DiscoveryProduct.objects.select_for_update().filter(source=locked_source)
            )
            product_map = {product.external_id: product for product in products}
            history = tuple(
                DiscoveryHistoryItem(
                    external_id=product.external_id,
                    is_present=product.is_present,
                    current_price=product.current_price,
                    reference_price=product.notification_reference_price,
                    position=product.position,
                )
                for product in products
            )
            comparison = compare_discovery_review(
                source_type=locked_source.source_type,
                baseline_established=locked_source.baseline_established,
                price_drop_percent=locked_source.price_drop_percent,
                history=history,
                items=normalized_items,
                is_complete=is_complete,
            )
            now = timezone.now()
            item_map = {item.external_id: item for item in normalized_items}
            event_count = notification_count = 0

            for external_id, item in item_map.items():
                product = product_map.get(external_id)
                if product is None:
                    product = DiscoveryProduct.objects.create(
                        source=locked_source,
                        external_id=external_id,
                        name=item.name,
                        url=item.url,
                        current_price=item.price,
                        notification_reference_price=item.price,
                        is_present=True,
                        position=item.position,
                        first_seen_at=now,
                        last_seen_at=now,
                        last_entered_at=now,
                    )
                    product_map[external_id] = product
                else:
                    product.name = item.name
                    product.url = item.url
                    product.current_price = item.price
                    product.position = item.position
                    product.last_seen_at = now
                    if external_id in comparison.reentries:
                        product.is_present = True
                        product.last_entered_at = now
                    if product.notification_reference_price is None and item.price is not None:
                        product.notification_reference_price = item.price
                    product.save(update_fields=(
                        "name", "url", "current_price", "position", "last_seen_at",
                        "is_present", "last_entered_at", "notification_reference_price",
                    ))

            event_specs = []
            event_specs.extend((key, DiscoveryEvent.EventType.BASELINE) for key in comparison.baseline)
            event_specs.extend((key, DiscoveryEvent.EventType.NEW) for key in comparison.new)
            event_specs.extend((key, DiscoveryEvent.EventType.REENTRY) for key in comparison.reentries)
            event_specs.extend((key, DiscoveryEvent.EventType.PRICE_DROP) for key in comparison.price_drops)
            event_specs.extend((key, DiscoveryEvent.EventType.EXIT) for key in comparison.exits)

            for external_id, event_type in event_specs:
                product = product_map[external_id]
                item = item_map.get(external_id)
                previous_price = next(
                    (entry.reference_price for entry in history if entry.external_id == external_id), None
                )
                previous_position = next(
                    (entry.position for entry in history if entry.external_id == external_id), None
                )
                if event_type == DiscoveryEvent.EventType.EXIT:
                    product.is_present = False
                    product.last_exited_at = now
                    product.save(update_fields=("is_present", "last_exited_at"))
                event = DiscoveryEvent.objects.create(
                    run=run,
                    product=product,
                    event_type=event_type,
                    previous_price=previous_price,
                    new_price=item.price if item else None,
                    previous_position=previous_position,
                    new_position=item.position if item else None,
                    data=_event_payload(locked_source, product, event_type, item),
                )
                event_count += 1
                notifiable_event_types = {
                    DiscoveryEvent.EventType.NEW,
                    DiscoveryEvent.EventType.PRICE_DROP,
                }
                if locked_source.source_type != DiscoverySource.SourceType.MERCADO_LIBRE_SELLER:
                    notifiable_event_types.add(DiscoveryEvent.EventType.REENTRY)
                if event_type in notifiable_event_types:
                    DiscoveryNotification.objects.create(
                        event=event,
                        payload=_event_payload(locked_source, product, event_type, item),
                    )
                    notification_count += 1
                    if item and item.price is not None:
                        product.notification_reference_price = item.price
                        product.save(update_fields=("notification_reference_price",))

            status = DiscoveryRun.Status.SUCCESS if is_complete else DiscoveryRun.Status.INCOMPLETE
            run.status = status
            run.finished_at = now
            run.pages_found = pages_found
            run.products_found = len(normalized_items)
            run.known_products = len(comparison.known)
            run.new_products = len(comparison.new)
            run.exits = len(comparison.exits)
            run.reentries = len(comparison.reentries)
            run.price_drops = len(comparison.price_drops)
            run.events_created = event_count
            run.notifications_created = notification_count
            run.save(update_fields=(
                "status", "finished_at", "pages_found", "products_found", "known_products",
                "new_products", "exits", "reentries", "price_drops", "events_created",
                "notifications_created",
            ))
            locked_source.last_run = run
            locked_source.last_status = status
            if status == DiscoveryRun.Status.SUCCESS:
                locked_source.last_successful_run = run
            if is_complete and not locked_source.baseline_established:
                locked_source.baseline_established = True
                locked_source.baseline_established_at = now
            locked_source.save(update_fields=(
                "last_run", "last_successful_run", "last_status", "baseline_established",
                "baseline_established_at", "updated_at",
            ))
        run.refresh_from_db()
        return run
    except Exception as exc:
        _finish_failed_run(run, exc)
        raise
