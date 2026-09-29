from copy import deepcopy
from .models import Supplier,EquipmentRevision
from .catalog import submit,publish

def seed(user):
    """Fictional and clearly labelled fixtures, never manufacturer assertions."""
    specs=dict(manufacturer='Учебный набор Робоскоп',configuration='Демонстрационная комплектация',source='Синтетический набор для проверки прототипа; не предложение производителя',
      payload_kg=1500,width_m=1,length_m=1.6,min_aisle_m=2.6,speed_m_s=1.2,runtime_h=6,charge_h=.3,power_kw=.4,lift_m=6,temp_min=0,temp_max=40,
      purchase=3000000,rental_month=110000,rental_scope='robots_chargers_software_service')
    out=[]
    for name,supplier_name,ops,rates,price in [
      ('Демо: универсальный погрузчик','Демо-поставщик А',['warehouse_rack_stacking','warehouse_pallet_transport','truck_loading'],[65,100,70],3000000),
      ('Демо: транспортная платформа','Демо-поставщик Б',['warehouse_pallet_transport'],[180],1800000),
      ('Демо: стеллажный погрузчик','Демо-поставщик А',['warehouse_rack_stacking','truck_loading'],[95,95],3500000)]:
        supplier,_=Supplier.objects.get_or_create(name=supplier_name,defaults={'demo':True})
        if EquipmentRevision.objects.filter(equipment__supplier=supplier,data__model=name).exists():continue
        d=deepcopy(specs);d.update(model=name,operations=ops,rates=dict(zip(ops,rates)),purchase=price)
        if 'платформа' in name:d.update(lift_m=0,width_m=.85,min_aisle_m=1.4,rental_month=75000)
        rev=submit(user,supplier,d,{'demo':True});publish(rev,user,'published','Учебные параметры; использование только как демонстрационного набора');out.append(rev)
    return out
