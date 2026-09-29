from django import forms
from .domain import TECH,OPERATIONS
from .finance import FIELDS

class FinanceForm(forms.Form):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for key,(label,default,lo,hi) in FIELDS.items():
            cls=forms.IntegerField if key in ['horizon','days_year','robots_per_charger'] else forms.FloatField
            self.fields[key]=cls(label=label,initial=default,min_value=lo,max_value=hi,required=key!='budget')

class EquipmentForm(forms.Form):
    manufacturer=forms.CharField(label='Производитель',max_length=200)
    model=forms.CharField(label='Модель',max_length=200)
    sku=forms.CharField(label='Артикул',required=False,max_length=120)
    configuration=forms.CharField(label='Комплектация',max_length=500)
    source=forms.CharField(label='Источник: документ, URL и дата',max_length=500)
    operations=forms.MultipleChoiceField(label='Операции',choices=OPERATIONS.items(),widget=forms.CheckboxSelectMultiple)
    purchase=forms.DecimalField(label='Цена покупки за единицу, руб.',required=False,min_value=0,max_digits=14,decimal_places=2)
    rental_month=forms.DecimalField(label='Аренда за единицу, руб./месяц',required=False,min_value=0,max_digits=14,decimal_places=2)
    rental_scope=forms.ChoiceField(label='Состав аренды',required=False,choices=[('','Не задан'),('robots_chargers_software_service','Роботы, зарядки, ПО и обслуживание')])
    estimated_fields=forms.CharField(label='Поля с допущениями (через запятую)',required=False)
    estimate_basis=forms.CharField(label='Основание оценки и аналоги',required=False,widget=forms.Textarea)
    confirm_identity=forms.BooleanField(label='Подтверждаю обновление этой модели и комплектации при совпадении',required=False)
    def __init__(self,*args,**kwargs):
        initial=kwargs.get('initial',{})
        if isinstance(initial.get('estimated_fields'),list):initial['estimated_fields']=','.join(initial['estimated_fields'])
        for k,v in initial.get('rates',{}).items():initial['rate_'+k]=v
        super().__init__(*args,**kwargs)
        for k,(label,lo,hi) in TECH.items():self.fields[k]=forms.FloatField(label=label,min_value=lo,max_value=hi,required=False)
        for k,label in OPERATIONS.items():self.fields['rate_'+k]=forms.FloatField(label=label+': операций в час без перемещения',min_value=.01,max_value=10000,required=False)
    def record(self):
        d=dict(self.cleaned_data)
        d['rates']={k:d.pop('rate_'+k) for k in OPERATIONS if d.get('rate_'+k) is not None}
        for k in list(d):
            if k.startswith('rate_'):d.pop(k)
        for k in ['purchase','rental_month']:
            if d[k] is not None:d[k]=float(d[k])
        d['estimated_fields']=[x.strip() for x in d['estimated_fields'].split(',') if x.strip()]
        return d
