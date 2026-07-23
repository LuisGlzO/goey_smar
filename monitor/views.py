from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .amazon_creators import safe_get_product_content
from .forms import ProductBulkUpdateForm, ProductForm
from .models import Alert, MonitorSettings, ObservationSource, Product, ProductCheck, ScraperAccount
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


def _refresh_product_image(product):
    content = safe_get_product_content(product.asin)
    if content is None:
        return False
    product.image_url = content.image_url
    product.image_refreshed_at = timezone.now()
    product.save(update_fields=("image_url", "image_refreshed_at", "updated_at"))
    return bool(content.image_url)


@login_required
@permission_required("monitor.view_product", raise_exception=True)
def products(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all")
    account = request.GET.get("account", "all")
    queryset = Product.objects.select_related("scraper_account")
    if query:
        queryset = queryset.filter(Q(asin__icontains=query) | Q(name__icontains=query))
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
@permission_required("monitor.add_product", raise_exception=True)
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        if _refresh_product_image(product):
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
        product = form.save()
        should_refresh = previous_asin != product.asin or not product.image_url
        if previous_asin != product.asin:
            Product.objects.filter(pk=product.pk).update(image_url="", image_refreshed_at=None)
            product.image_url = ""
            product.image_refreshed_at = None
        if should_refresh and not _refresh_product_image(product):
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
    for field in ("cooldown_minutes", "max_alerts_per_day"):
        if form.cleaned_data[field] is not None:
            updates[field] = form.cleaned_data[field]
    with transaction.atomic():
        updated = Product.objects.filter(pk__in=form.cleaned_data["product_ids"]).update(**updates)
    messages.success(request, f"Productos actualizados: {updated}.")
    return redirect("products")


def _cooldown_state(product, monitor_settings, now):
    last_sent = product.alerts.filter(status=Alert.Status.SENT).first()
    if not last_sent:
        return {"label": "Disponible", "blocked": False, "remaining_minutes": 0}
    anti_until = last_sent.created_at + timedelta(
        minutes=monitor_settings.anti_false_restock_cooldown_minutes
    )
    normal_until = last_sent.created_at + timedelta(minutes=product.cooldown_minutes)
    blocked_until = max(anti_until, normal_until)
    if blocked_until <= now:
        return {"label": "Disponible", "blocked": False, "remaining_minutes": 0}
    seconds = max(int((blocked_until - now).total_seconds()), 0)
    minutes = (seconds + 59) // 60
    return {"label": f"Cooldown: {minutes} min", "blocked": True, "remaining_minutes": minutes}


@login_required
@permission_required("monitor.send_manual_alert", raise_exception=True)
def manual_alerts(request):
    query = request.GET.get("q", "").strip()
    products = Product.objects.filter(is_active=True)
    if query:
        products = products.filter(Q(asin__icontains=query) | Q(name__icontains=query))
    settings = MonitorSettings.load()
    now = timezone.now()
    rows = [{"product": product, "cooldown": _cooldown_state(product, settings, now)} for product in products]
    return render(request, "monitor/manual_alerts.html", {"rows": rows, "query": query})


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
    return redirect("manual_alerts")
