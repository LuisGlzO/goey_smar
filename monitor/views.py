from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .amazon_creators import creators_api_is_configured, get_products_content, safe_get_product_content
from .forms import AffiliateLinkGeneratorForm, ProductBulkUpdateForm, ProductForm, ProductGroupForm
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
    accounts = list(ScraperAccount.objects.all())
    account_snapshots = []
    cart_items = []
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
            cart_items.extend(
                list(run.cart_items.select_related("scraper_account").all())
            )

    catalog_products = list(Product.objects.select_related("scraper_account"))
    catalog_asins = {product.asin for product in catalog_products}
    cart_asins_by_account = {account.key: set() for account in accounts}
    accounts_with_snapshot = {
        snapshot["account"].key for snapshot in account_snapshots if snapshot["run"]
    }
    for item in cart_items:
        cart_asins_by_account[item.scraper_account_id].add(item.asin)

    only_in_cart = [item for item in cart_items if item.asin not in catalog_asins]
    only_in_catalog = [
        product
        for product in catalog_products
        if product.scraper_account_id in accounts_with_snapshot
        if product.asin not in cart_asins_by_account.get(product.scraper_account_id, set())
    ]
    return render(request, "monitor/catalog_cart_comparison.html", {
        "only_in_cart": only_in_cart,
        "only_in_catalog": only_in_catalog,
        "account_snapshots": account_snapshots,
    })


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
    )
    return render(request, "monitor/product_groups.html", {"groups": groups})


@login_required
@permission_required("monitor.add_product", raise_exception=True)
def product_group_create(request):
    form = ProductGroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
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
@permission_required("monitor.delete_product", raise_exception=True)
def product_group_delete(request, group_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    group = get_object_or_404(ProductGroup, pk=group_id)
    name = group.name
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
    elif group_key == "ungrouped":
        products = products.filter(group__isnull=True)
        selected_group = "ungrouped"
    elif group_key:
        if not group_key.isdigit():
            raise Http404("Grupo no encontrado.")
        selected_group = get_object_or_404(ProductGroup, pk=group_key)
        products = products.filter(group=selected_group)

    rows = [{"product": product} for product in products] if showing_products else []
    groups = []
    ungrouped_count = 0
    if not showing_products:
        groups = ProductGroup.objects.annotate(
            active_product_count=Count("products", filter=Q(products__is_active=True))
        )
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
