from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("productos/", views.products, name="products"),
    path("productos/nuevo/", views.product_create, name="product_create"),
    path("productos/<int:product_id>/editar/", views.product_edit, name="product_edit"),
    path("productos/actualizar-seleccion/", views.products_bulk_update, name="products_bulk_update"),
    path("grupos/", views.product_groups, name="product_groups"),
    path("grupos/nuevo/", views.product_group_create, name="product_group_create"),
    path("grupos/<int:group_id>/editar/", views.product_group_edit, name="product_group_edit"),
    path("grupos/<int:group_id>/eliminar/", views.product_group_delete, name="product_group_delete"),
    path("comparacion-catalogo-carritos/", views.catalog_cart_comparison, name="catalog_cart_comparison"),
    path("generador-enlaces/", views.affiliate_link_generator, name="affiliate_link_generator"),
    path("alertas/", views.manual_alerts, name="manual_alerts"),
    path("alertas/<int:product_id>/enviar/", views.send_manual_alert, name="send_manual_alert"),
]
