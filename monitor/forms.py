from django import forms

from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "asin", "name", "affiliate_url", "max_price", "priority", "is_active",
            "cooldown_minutes", "max_alerts_per_day", "significant_price_drop_percent",
        )
        labels = {
            "asin": "ASIN",
            "name": "Nombre",
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
            "affiliate_url": "Opcional. Tiene prioridad sobre el enlace generado automáticamente.",
        }
        widgets = {
            "asin": forms.TextInput(attrs={"maxlength": 10, "autocomplete": "off"}),
            "name": forms.TextInput(),
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
        if cleaned.get("cooldown_minutes") is None and cleaned.get("max_alerts_per_day") is None:
            raise forms.ValidationError("Indica un cooldown, un límite diario o ambos.")
        return cleaned
