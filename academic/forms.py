"""Formularios internos para la gestión del taller de pastelería."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import BakeryOrder, BakeryOrderItem, BakeryProductOption, BOMItem, Material


class StaffUserCreationForm(UserCreationForm):
    """Valida las credenciales de un nuevo gestor sin permitir privilegios de superusuario."""

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class BakeryOrderForm(forms.ModelForm):
    """Datos de contacto, entrega y descripción del pedido."""

    class Meta:
        model = BakeryOrder
        fields = [
            'customer_name',
            'contact_phone',
            'order_details',
            'delivery_date',
            'delivery_time',
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'order_details': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'delivery_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'delivery_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delivery_date'].widget.attrs['min'] = timezone.localdate().isoformat()

    def clean_delivery_date(self):
        delivery_date = self.cleaned_data.get('delivery_date')
        if delivery_date and delivery_date < timezone.localdate():
            raise forms.ValidationError('La fecha de entrega no puede ser anterior a hoy.')
        return delivery_date


class BakeryOrderItemForm(forms.ModelForm):
    """Línea de torta común o personalizada, conservando el nombre como historial."""

    product_option = forms.ModelChoiceField(
        queryset=BakeryProductOption.objects.none(),
        empty_label='Selecciona una torta',
        widget=forms.Select(attrs={'class': 'form-select cake-option'}),
    )
    product_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre de la torta personalizada',
            'aria-label': 'Nombre de la torta personalizada',
        }),
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'step': '1',
            'placeholder': 'Cant.',
            'aria-label': 'Cantidad de productos',
        }),
    )
    unit_price = forms.DecimalField(
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '0.01',
            'placeholder': 'Precio',
            'aria-label': 'Precio unitario',
        }),
    )

    class Meta:
        model = BakeryOrderItem
        fields = ['product_option', 'product_name', 'quantity', 'unit_price', 'notes']
        widgets = {
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tamaño, decoración...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product_option'].queryset = BakeryProductOption.objects.filter(is_active=True)
        if self.instance.pk and not self.is_bound:
            option = self.instance.product_option
            if not option:
                option = self.fields['product_option'].queryset.filter(
                    name=self.instance.product_name
                ).first()
            if option and option.is_active:
                self.initial['product_option'] = option.pk
            else:
                self.initial['product_option'] = BakeryProductOption.objects.filter(
                    is_customized=True, is_active=True
                ).values_list('pk', flat=True).first()

    def clean(self):
        cleaned_data = super().clean()
        option = cleaned_data.get('product_option')
        product_name = cleaned_data.get('product_name', '').strip()
        if option is None:
            return cleaned_data
        if option.is_customized:
            if not product_name:
                self.add_error('product_name', 'Indica el nombre o tipo de torta personalizada.')
        else:
            cleaned_data['product_name'] = option.name
            cleaned_data['notes'] = ''
        return cleaned_data


class BOMItemForm(forms.ModelForm):
    """Ingrediente y cantidad que se reservará para producción."""

    quantity = forms.DecimalField(
        min_value=0.01,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0.01',
            'step': '0.01',
            'placeholder': 'Cant.',
            'aria-label': 'Cantidad del ingrediente',
        }),
    )

    class Meta:
        model = BOMItem
        fields = ['material', 'quantity', 'notes']
        widgets = {
            'material': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Detalle opcional'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_material_id = self.instance.material_id
        self.fields['material'].queryset = Material.objects.filter(
            Q(is_active=True) | Q(pk=current_material_id)
        ).order_by('name')


BakeryOrderItemFormSet = inlineformset_factory(
    BakeryOrder,
    BakeryOrderItem,
    form=BakeryOrderItemForm,
    extra=1,
    can_delete=True,
)

BOMItemFormSet = inlineformset_factory(
    BakeryOrder,
    BOMItem,
    form=BOMItemForm,
    extra=1,
    can_delete=True,
)


class MaterialForm(forms.ModelForm):
    """Valida alta y edición de ingredientes, incluidas existencias y nivel mínimo."""

    class Meta:
        model = Material
        fields = ['name', 'stock', 'minimum_stock', 'unit', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej.: Harina sin polvos'}),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
            }),
            'minimum_stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.01',
            }),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
