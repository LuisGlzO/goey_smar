import re

from django import forms
from django.db.models import Q

from .models import Product, ProductGroup, ScraperAccount


class ProductGroupForm(forms.ModelForm):
    class Meta:
        model = ProductGroup
        fields = ("name", "description", "color")
        labels = {
            "name": "Nombre",
            "description": "Descripción",
            "color": "Color",
        }
        help_texts = {
            "description": "Opcional. Se mostrará en la card del grupo.",
            "color": "Color identificador del grupo.",
        }
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "color": forms.TextInput(attrs={"type": "color"}),
        }


class ProductGroupAssignmentForm(forms.Form):
    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
    )

    def __init__(self, *args, group, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["products"].queryset = Product.objects.filter(
            Q(group__isnull=True) | Q(group=group)
        )


class ProductForm(forms.ModelForm):
    name = forms.CharField(
        required=False,
        max_length=250,
        label="Nombre",
        help_text=(
            "Opcional. Si lo dejas vacío, se obtendrá desde Creators API. "
            "Es el nombre público que se mostrará en Telegram."
        ),
    )

    class Meta:
        model = Product
        fields = (
            "asin", "name", "observations", "group", "scraper_account", "affiliate_url", "max_price",
            "priority", "is_active", "cooldown_minutes", "max_alerts_per_day",
            "significant_price_drop_percent",
        )
        labels = {
            "asin": "ASIN",
            "name": "Nombre",
            "observations": "Observaciones internas",
            "group": "Grupo",
            "scraper_account": "Cuenta de Amazon",
            "affiliate_url": "URL de afiliado",
            "max_price": "Precio máximo",
            "priority": "Prioridad",
            "is_active": "Producto activo",
            "cooldown_minutes": "Cooldown (minutos)",
            "max_alerts_per_day": "Límite de alertas diarias",
            "significant_price_drop_percent": "Caída significativa de precio (%)",
        }
        help_texts = {
            "asin": "Código ASIN de 10 caracteres.",
            "name": "Nombre público exacto que se mostrará en la alerta de Telegram.",
            "observations": "Anotaciones internas. Nunca se incluyen en las alertas.",
            "affiliate_url": "Opcional. Tiene prioridad sobre el enlace generado automáticamente.",
        }
        widgets = {
            "asin": forms.TextInput(attrs={"maxlength": 10, "autocomplete": "off"}),
            "name": forms.TextInput(),
            "observations": forms.Textarea(attrs={"rows": 3}),
            "affiliate_url": forms.URLInput(),
            "max_price": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
            "cooldown_minutes": forms.NumberInput(attrs={"min": 0}),
            "max_alerts_per_day": forms.NumberInput(attrs={"min": 0}),
            "significant_price_drop_percent": forms.NumberInput(attrs={"min": 0, "step": "0.01"}),
        }

    def clean_asin(self):
        asin = self.cleaned_data["asin"].strip().upper()
        if len(asin) != 10 or not asin.isalnum():
            raise forms.ValidationError("El ASIN debe contener exactamente 10 letras o números.")
        return asin


class ProductBulkUpdateForm(forms.Form):
    product_ids = forms.CharField(required=False, widget=forms.HiddenInput)
    cooldown_minutes = forms.IntegerField(required=False, min_value=0, label="Cooldown (minutos)")
    max_alerts_per_day = forms.IntegerField(required=False, min_value=0, label="Límite de alertas diarias")
    max_price = forms.DecimalField(
        required=False, min_value=0, max_digits=12, decimal_places=2, label="Precio máximo"
    )
    is_active = forms.TypedChoiceField(
        required=False,
        choices=(("", "No modificar"), ("true", "Activo"), ("false", "Inactivo")),
        coerce=lambda value: value == "true",
        empty_value=None,
        label="Estado",
    )
    scraper_account = forms.ModelChoiceField(
        required=False,
        queryset=ScraperAccount.objects.all(),
        empty_label="No modificar",
        label="Cuenta de Amazon / carrito",
    )

    def clean_product_ids(self):
        values = []
        for raw_id in self.cleaned_data["product_ids"].split(","):
            raw_id = raw_id.strip()
            if raw_id.isdigit():
                values.append(int(raw_id))
        if not values:
            raise forms.ValidationError("Selecciona al menos un producto.")
        return list(dict.fromkeys(values))

    def clean(self):
        cleaned = super().clean()
        editable_fields = (
            "cooldown_minutes", "max_alerts_per_day", "max_price", "is_active", "scraper_account",
        )
        if all(cleaned.get(field) is None for field in editable_fields):
            raise forms.ValidationError("Indica al menos un campo para actualizar.")
        return cleaned


class AffiliateLinkGeneratorForm(forms.Form):
    asins = forms.CharField(
        label="ASIN de Amazon",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "autocomplete": "off",
            "spellcheck": "false",
            "placeholder": "Ej. B0G3CY83L5, B0ABC12345",
            "data-asin-input": "",
        }),
        help_text="Introduce hasta 50 ASIN, separados por comas, espacios o saltos de línea.",
    )

    def clean_asins(self):
        values = [
            value.upper()
            for value in re.split(r"[\s,;]+", self.cleaned_data["asins"].strip())
            if value
        ]
        values = list(dict.fromkeys(values))
        invalid = [value for value in values if not re.fullmatch(r"[A-Z0-9]{10}", value)]
        if invalid:
            raise forms.ValidationError(
                "Estos ASIN no tienen exactamente 10 letras o números: "
                + ", ".join(invalid[:5])
            )
        if len(values) > 50:
            raise forms.ValidationError("Puedes consultar hasta 50 ASIN a la vez.")
        return values
