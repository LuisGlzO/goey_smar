from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, Exists, IntegerField, Max, OuterRef, Q, Value, When
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .amazon_creators import creators_api_is_configured, get_products_content, safe_get_product_content
from .forms import (
    AffiliateLinkGeneratorForm, ProductBulkUpdateForm, ProductForm,
    ProductGroupAssignmentForm, ProductGroupForm,
)
from .models import (
    Alert, MonitorRun, MonitorSettings, ObservationSource, Product, ProductCheck,
    ProductGroup, ScraperAccount,
)
from .services import request_product_alert


REASON_MESSAGES = {
    "anti_false_restock_cooldown": "No se puede enviar: está activo el cooldown anti-falso-restock.",
    "cooldown": "No se puede enviar: el producto continúa en cooldown.",
    "daily_limit": "No se puede enviar: se alcanzó el límite diario de alertas.",
    "alert_in_progress": "Ya hay un envío de este producto en proceso.",
    "product_inactive": "No se puede enviar una alerta de un producto inactivo.",
    "telegram_error": "Telegram rechazó el envío. Puede intentarlo nuevamente.",
}


@login_required
def dashboard(request):
    return render(request, "monitor/dashboard.html")


@login_required
@permission_required("monitor.view_product", raise_exception=True)
def catalog_cart_comparison(request):
    status_filter = request.GET.get("status", "all")
    allowed_status_filters = {"all", "reconciled", "absent", "intentional", "misaligned"}
    if status_filter not in allowed_status_filters:
        status_filter = "all"
    accounts = list(ScraperAccount.objects.all())
    account_snapshots = []
    cart_items_by_asin = {}
    accounts_with_snapshot = set()
    for account in accounts:
        run = (
            MonitorRun.objects.filter(
                worker_key=f"scraper:{account.key}",
                status=MonitorRun.Status.SUCCESS,
            )
            .order_by("-finished_at", "-pk")
            .first()
        )
        account_snapshots.append({"account": account, "run": run})
        if run:
            accounts_with_snapshot.add(account.key)
            for item in run.cart_items.select_related("scraper_account").all():
                cart_items_by_asin.setdefault(item.asin, {})[account.key] = item

    catalog_products = list(Product.objects.select_related("scraper_account"))
    catalog_asins = {product.asin for product in catalog_products}
    all_accounts_have_snapshot = len(accounts_with_snapshot) == len(accounts)
    catalog_rows = []
    for product in catalog_products:
        items_by_account = cart_items_by_asin.get(product.asin, {})
        cart_states = [
            {
                "account": account,
                "has_snapshot": account.key in accounts_with_snapshot,
                "present": account.key in items_by_account,
            }
            for account in accounts
        ]
        present_account_ids = set(items_by_account)
        if product.intentionally_not_in_cart and present_account_ids:
            diagnostic = "intentional_present"
            diagnostic_label = "Marcado intencional, pero reapareció"
        elif not all_accounts_have_snapshot:
            diagnostic = "incomplete"
            diagnostic_label = "Información incompleta"
        elif not present_account_ids:
            diagnostic = "intentional_absence" if product.intentionally_not_in_cart else "absent"
            diagnostic_label = (
                "Ausencia intencional" if product.intentionally_not_in_cart else "Ausente de los carritos"
            )
        elif product.scraper_account_id not in present_account_ids:
            diagnostic = "misaligned"
            diagnostic_label = "Asignación desalineada"
        else:
            diagnostic = "reconciled"
            diagnostic_label = "Conciliado"
        catalog_rows.append({
            "product": product,
            "cart_states": cart_states,
            "diagnostic": diagnostic,
            "diagnostic_label": diagnostic_label,
        })

    status_counts = {
        "all": len(catalog_rows),
        "reconciled": sum(row["diagnostic"] == "reconciled" for row in catalog_rows),
        "absent": sum(row["diagnostic"] == "absent" for row in catalog_rows),
        "misaligned": sum(row["diagnostic"] == "misaligned" for row in catalog_rows),
        "intentional": sum(
            row["diagnostic"] in {"intentional_absence", "intentional_present"}
            for row in catalog_rows
        ),
    }
    if status_filter == "reconciled":
        catalog_rows = [row for row in catalog_rows if row["diagnostic"] == "reconciled"]
    elif status_filter == "absent":
        catalog_rows = [row for row in catalog_rows if row["diagnostic"] == "absent"]
    elif status_filter == "misaligned":
        catalog_rows = [row for row in catalog_rows if row["diagnostic"] == "misaligned"]
    elif status_filter == "intentional":
        catalog_rows = [
            row for row in catalog_rows
            if row["diagnostic"] in {"intentional_absence", "intentional_present"}
        ]

    external_rows = []
    for asin, items_by_account in cart_items_by_asin.items():
        if asin in catalog_asins:
            continue
        representative = next(iter(items_by_account.values()))
        external_rows.append({
            "asin": asin,
            "item": representative,
            "cart_states": [
                {
                    "account": account,
                    "has_snapshot": account.key in accounts_with_snapshot,
                    "present": account.key in items_by_account,
                }
                for account in accounts
            ],
        })
    external_rows.sort(key=lambda row: row["asin"])
    return render(request, "monitor/catalog_cart_comparison.html", {
        "catalog_rows": catalog_rows,
        "external_rows": external_rows,
        "account_snapshots": account_snapshots,
        "status_filter": status_filter,
        "status_counts": status_counts,
    })


@login_required
@permission_required("monitor.change_product", raise_exception=True)
def toggle_product_cart_intention(request, product_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    with transaction.atomic():
        product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
        product.intentionally_not_in_cart = not product.intentionally_not_in_cart
        product.save(update_fields=("intentionally_not_in_cart", "updated_at"))
    if product.intentionally_not_in_cart:
        messages.success(request, f'"{product.name}" se marcó como solo en el sistema a propósito.')
    else:
        messages.success(request, f'"{product.name}" volverá a evaluarse como posible discrepancia.')
    status_filter = request.GET.get("status", "all")
    if status_filter not in {"reconciled", "absent", "intentional", "misaligned"}:
        return redirect("catalog_cart_comparison")
    return redirect(f'{reverse("catalog_cart_comparison")}?status={status_filter}')


@login_required
@permission_required("monitor.view_product", raise_exception=True)
def affiliate_link_generator(request):
    form = AffiliateLinkGeneratorForm(request.POST or None)
    rows = []
    api_error = ""
    if request.method == "POST" and form.is_valid():
        asins = form.cleaned_data["asins"]
        if not creators_api_is_configured():
            api_error = "Creators API no está configurada en este entorno."
        else:
            try:
                content_by_asin = {}
                for index in range(0, len(asins), 10):
                    content_by_asin.update(get_products_content(asins[index:index + 10]))
                rows = [
                    {"asin": asin, "content": content_by_asin.get(asin)}
                    for asin in asins
                ]
            except Exception:
                api_error = (
                    "No fue posible consultar Creators API en este momento. "
                    "Inténtalo nuevamente."
                )
    return render(request, "monitor/affiliate_link_generator.html", {
        "form": form,
        "rows": rows,
        "api_error": api_error,
    })


def _apply_creators_content(product, content, *, fill_name=False):
    if content is None:
        return False
    if fill_name:
        product.name = content.title
    product.image_url = content.image_url
    product.image_refreshed_at = timezone.now()
    return bool(content.image_url)


@login_required
@permission_required("monitor.view_product", raise_exception=True)
def products(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all")
    account = request.GET.get("account", "all")
    queryset = Product.objects.select_related("scraper_account", "group")
    if query:
        queryset = queryset.filter(
            Q(asin__icontains=query) | Q(name__icontains=query) | Q(observations__icontains=query)
        )
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)
    else:
        status = "all"
    if account != "all" and ScraperAccount.objects.filter(pk=account).exists():
        queryset = queryset.filter(scraper_account_id=account)
    else:
        account = "all"
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(request, "monitor/products.html", {
        "page": page, "query": query, "status": status, "account": account,
        "scraper_accounts": ScraperAccount.objects.all(),
    })


@login_required
@permission_required("monitor.view_product", raise_exception=True)
def product_groups(request):
    groups = ProductGroup.objects.annotate(
        product_count=Count("products"),
        active_product_count=Count("products", filter=Q(products__is_active=True)),
    ).order_by("display_order", "name", "pk")
    return render(request, "monitor/product_groups.html", {"groups": groups})


@login_required
@permission_required("monitor.add_product", raise_exception=True)
def product_group_create(request):
    form = ProductGroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        group.display_order = (ProductGroup.objects.aggregate(value=Max("display_order"))["value"] or 0) + 1
        group.save()
        messages.success(request, "Grupo creado correctamente.")
        return redirect("product_groups")
    return render(request, "monitor/product_group_form.html", {"form": form, "group": None})


@login_required
@permission_required("monitor.change_product", raise_exception=True)
def product_group_edit(request, group_id):
    group = get_object_or_404(ProductGroup, pk=group_id)
    form = ProductGroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Grupo actualizado correctamente.")
        return redirect("product_groups")
    return render(request, "monitor/product_group_form.html", {"form": form, "group": group})


@login_required
@permission_required("monitor.change_product", raise_exception=True)
def product_group_products(request, group_id):
    group = get_object_or_404(ProductGroup, pk=group_id)
    form = ProductGroupAssignmentForm(request.POST or None, group=group)
    if request.method == "POST" and form.is_valid():
        selected_product_ids = form.ordered_product_ids
        with transaction.atomic():
            current = list(Product.objects.select_for_update().filter(
                Q(group=group) | Q(pk__in=selected_product_ids)
            ))
            by_id = {product.pk: product for product in current}
            selected = set(selected_product_ids)
            for product in current:
                if product.group_id == group.pk and product.pk not in selected:
                    product.group = None
                    product.group_order = 0
            for position, product_id in enumerate(selected_product_ids):
                product = by_id[product_id]
                product.group = group
                product.group_order = position
            Product.objects.bulk_update(current, ("group", "group_order"))
        messages.success(request, "Productos del grupo actualizados correctamente.")
        return redirect("product_group_products", group_id=group.pk)

    assigned_products = list(group.products.order_by("group_order", "name", "asin", "pk"))
    available_products = list(Product.objects.filter(group__isnull=True).order_by("name", "asin"))
    return render(request, "monitor/product_group_products.html", {
        "form": form,
        "group": group,
        "assigned_products": assigned_products,
        "available_products": available_products,
        "total_products": len(assigned_products) + len(available_products),
    })


@login_required
@permission_required("monitor.change_product", raise_exception=True)
def product_groups_order(request):
    groups = list(ProductGroup.objects.order_by("display_order", "name", "pk"))
    if request.method == "POST":
        raw_ids = request.POST.getlist("groups")
        expected = {str(group.pk) for group in groups}
        if (
            len(raw_ids) != len(set(raw_ids))
            or any(not value.isdigit() for value in raw_ids)
            or set(raw_ids) != expected
        ):
            messages.error(request, "El orden enviado no coincide con los grupos existentes.")
        else:
            with transaction.atomic():
                locked = {
                    group.pk: group
                    for group in ProductGroup.objects.select_for_update().filter(pk__in=raw_ids)
                }
                for position, raw_id in enumerate(raw_ids):
                    locked[int(raw_id)].display_order = position
                ProductGroup.objects.bulk_update(locked.values(), ("display_order",))
            messages.success(request, "Orden de grupos actualizado correctamente.")
            return redirect("product_groups")
    return render(request, "monitor/product_groups_order.html", {"groups": groups})


@login_required
@permission_required("monitor.delete_product", raise_exception=True)
def product_group_delete(request, group_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    group = get_object_or_404(ProductGroup, pk=group_id)
    name = group.name
    with transaction.atomic():
        Product.objects.filter(group=group).update(group=None, group_order=0)
        group.delete()
    messages.success(request, f'Grupo "{name}" eliminado. Sus productos quedaron sin grupo.')
    return redirect("product_groups")


@login_required
@permission_required("monitor.add_product", raise_exception=True)
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        content = safe_get_product_content(product.asin)
        if not product.name and (content is None or not content.title):
            form.add_error(
                "name",
                "Creators API no devolvió un nombre. Escribe uno o intenta nuevamente.",
            )
            return render(request, "monitor/product_form.html", {"form": form, "product": None})
        has_image = _apply_creators_content(product, content, fill_name=not product.name)
        if product.group_id:
            product.group_order = (
                Product.objects.filter(group_id=product.group_id).aggregate(value=Max("group_order"))["value"] or 0
            ) + 1
        product.save()
        if has_image:
            messages.success(request, "Producto creado y fotografía obtenida desde Amazon.")
        else:
            messages.warning(request, "Producto creado. Creators API no devolvió una fotografía.")
        return redirect("products")
    return render(request, "monitor/product_form.html", {"form": form, "product": None})


@login_required
@permission_required("monitor.change_product", raise_exception=True)
def product_edit(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    previous_group_id = product.group_id
    previous_asin = product.asin
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        needs_name = not product.name
        should_refresh = needs_name or previous_asin != product.asin or not product.image_url
        content = safe_get_product_content(product.asin) if should_refresh else None
        if needs_name and (content is None or not content.title):
            form.add_error(
                "name",
                "Creators API no devolvió un nombre. Escribe uno o intenta nuevamente.",
            )
            return render(request, "monitor/product_form.html", {"form": form, "product": product})
        if previous_asin != product.asin:
            product.image_url = ""
            product.image_refreshed_at = None
        has_image = _apply_creators_content(product, content, fill_name=needs_name) if should_refresh else True
        if product.group_id != previous_group_id:
            product.group_order = 0
            if product.group_id:
                product.group_order = (
                    Product.objects.filter(group_id=product.group_id).aggregate(value=Max("group_order"))["value"] or 0
                ) + 1
        product.save()
        if should_refresh and not has_image:
            messages.warning(request, "Cambios guardados, pero Creators API no devolvió una fotografía.")
        else:
            messages.success(request, "Producto actualizado correctamente.")
        return redirect("products")
    return render(request, "monitor/product_form.html", {"form": form, "product": product})


@login_required
@permission_required("monitor.change_product", raise_exception=True)
def products_bulk_update(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    form = ProductBulkUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
        return redirect("products")
    updates = {}
    for field in ("cooldown_minutes", "max_alerts_per_day", "max_price", "is_active"):
        if form.cleaned_data[field] is not None:
            updates[field] = form.cleaned_data[field]
    if form.cleaned_data["scraper_account"] is not None:
        updates["scraper_account"] = form.cleaned_data["scraper_account"]
    with transaction.atomic():
        updated = Product.objects.filter(pk__in=form.cleaned_data["product_ids"]).update(**updates)
    messages.success(request, f"Productos actualizados: {updated}.")
    return redirect("products")


@login_required
@permission_required("monitor.send_manual_alert", raise_exception=True)
def manual_alerts(request):
    query = request.GET.get("q", "").strip()
    group_key = request.GET.get("group", "").strip()
    products = Product.objects.filter(is_active=True).select_related("group")
    selected_group = None
    showing_products = bool(query or group_key)
    if query:
        products = products.filter(
            Q(asin__icontains=query) | Q(name__icontains=query)
        )
        group_key = ""
        products = products.annotate(
            manual_group_order=Case(
                When(group__isnull=True, then=Value(2147483647)),
                default="group__display_order",
                output_field=IntegerField(),
            )
        ).order_by("manual_group_order", "group_order", "name", "asin", "pk")
    elif group_key == "ungrouped":
        products = products.filter(group__isnull=True).order_by("name", "asin", "pk")
        selected_group = "ungrouped"
    elif group_key:
        if not group_key.isdigit():
            raise Http404("Grupo no encontrado.")
        selected_group = get_object_or_404(ProductGroup, pk=group_key)
        products = products.filter(group=selected_group).order_by("group_order", "name", "asin", "pk")

    if showing_products:
        monitor_settings = MonitorSettings.load()
        cooldown_minutes = monitor_settings.anti_false_restock_cooldown_minutes
        if cooldown_minutes > 0:
            cutoff = timezone.now() - timedelta(minutes=cooldown_minutes)
            products = products.annotate(
                anti_false_active=Exists(
                    Alert.objects.filter(
                        product_id=OuterRef("pk"),
                        status=Alert.Status.SENT,
                        created_at__gte=cutoff,
                    )
                )
            )

    rows = [{"product": product} for product in products] if showing_products else []
    groups = []
    ungrouped_count = 0
    if not showing_products:
        groups = ProductGroup.objects.annotate(
            active_product_count=Count("products", filter=Q(products__is_active=True))
        ).order_by("display_order", "name", "pk")
        ungrouped_count = Product.objects.filter(is_active=True, group__isnull=True).count()
    return render(request, "monitor/manual_alerts.html", {
        "rows": rows,
        "groups": groups,
        "query": query,
        "group_key": group_key,
        "selected_group": selected_group,
        "showing_products": showing_products,
        "ungrouped_count": ungrouped_count,
    })


@login_required
@permission_required("monitor.send_manual_alert", raise_exception=True)
def send_manual_alert(request, product_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    product = get_object_or_404(Product, pk=product_id)
    check = ProductCheck.objects.create(
        product=product,
        source=ObservationSource.MANUAL,
        requested_by=request.user,
        availability=ProductCheck.Availability.AVAILABLE,
        product_url=product.affiliate_url,
        raw_text=f"Solicitud manual por {request.user.get_username()}",
    )
    alert = request_product_alert(
        product, check, ObservationSource.MANUAL,
        requested_by=request.user, monitor_settings=MonitorSettings.load(),
    )
    if alert.status == Alert.Status.SENT:
        messages.success(request, f"Alerta de {product.name} enviada correctamente.")
    elif alert.status == Alert.Status.FAILED:
        messages.error(request, REASON_MESSAGES.get(alert.reason, f"No se pudo enviar: {alert.details}"))
    else:
        messages.warning(request, REASON_MESSAGES.get(alert.reason, f"No se puede enviar: {alert.reason}."))
    group_key = request.POST.get("group", "").strip()
    if group_key == "ungrouped" or group_key.isdigit():
        return redirect(f"{reverse('manual_alerts')}?group={group_key}")
    return redirect("manual_alerts")
