"""Словарь меток: добавлять алиасы здесь, не меняя pipeline."""
import re

VERSION = '2026-09-28-v3'
ALIASES = {
 'length':[r'^длина(?: робота)?(?:,.*)?$'],
 'width':[r'^ширина(?: робота)?(?:,.*)?$'],
 'height':[r'^высота(?: робота)?(?:,.*)?$'],
 'robot_mass':[r'^(?:вес|масса)(?: робота)?(?:,.*)?$'],
 'payload':[r'грузопод[ъь]емност',r'максимальн\w* (?:вес|масса) (?:поднят|груза)'],
 'towing_capacity':[r'тягов\w* усили'],
 'travel_speed':[r'скорост\w* (?:перемещени|движени|передвижени)'],
 'loaded_speed':[r'скорост\w*.*с грузом'],
 'unloaded_speed':[r'скорост\w*.*без груза'],
 'turning_diameter':[r'диаметр разворота'],
 'lift_height':[r'высота под[ъь]ем'],
 'max_grade':[r'угол под[ъь]ем',r'преодолеваем\w* уклон'],
 'navigation_type':[r'(?:тип|способ[ыа]?) навигаци',r'^навигаци[яи]$'],
 'positioning_accuracy':[r'точност\w* позиционировани.*(?:мм|миллиметр)',r'^точность позиционирования$'],
 'angular_accuracy':[r'точност\w* позиционировани.*(?:°|градус)'],
 'qr_precise_positioning':[r'точн\w* позиционировани.*qr'],
 'automatic_braking':[r'автоматическ\w* торможени'],
 'emergency_buttons':[r'кноп(?:ка|ки|ок|ку) аварийн\w* остановк',r'аварийн\w* (?:стоп|кнопк)',r'\be[- ]?stop\b'],
 'obstacle_avoidance_3d':[r'3d[- ]?обход препятств',r'трехмерн\w* обход препятств'],
 'bumper':[r'защитн\w* бампер'],
 'battery_capacity':[r'[её]мкост\w* батаре'],
 'runtime':[r'время работ',r'время автономн',r'автономност'],
 'charging_time':[r'время зар(?:яд|яда)|длительност\w* зарядк'],
 'battery_life':[r'ресурс батаре',r'срок службы батаре'],
 'battery_voltage':[r'^(?:подключение|напряжение)(?:,.*)?$'],
 'charging_requirements':[r'способ зарядк'],
 'charging_input':[r'ручная зарядк'],
 'display':[r'экран|дисплей'], 'speaker':[r'динамик|звуков\w* оповещени'],
 'open_api':[r'открыт\w* api'],
 'shelf_recognition':[r'распознаван\w* пол[ко]'],
 'pallet_recognition':[r'распознаван\w* (?:поддон|паллет)'],
 'wifi_roaming':[r'wi[- ]?fi роуминг'],
 'operating_temperature':[r'рабочая температура|температур\w* (?:эксплуатаци|работы)'],
 'ip_rating':[r'степень защит',r'класс защит\w* ip'],
 'integration':[r'интеграци\w* с по'],
 'connectivity':[r'интерфейс\w* подключени|вид беспроводн\w* связ'],
 'handled_load':[r'перевозим\w* груз'],
 'min_aisle_width':[r'минимальн\w* ширин\w* проезд'],
 'compatible_pallet':[r'тип поддон'], 'load_center':[r'расстояние от центра нагрузки'],
 'obstacle_height':[r'высота преодолеваем\w* препятств'],
 'floor_requirements':[r'требован\w* к полу'],
 'omnidirectional':[r'смена направления без разворота'],
 'series':[r'^серия$'], 'manufacturer':[r'^бренд$|^производитель$'],
 'battery_chemistry':[r'^питание$'],
}
DIMENSIONS = re.compile(r'^(?:габаритн\w* размер\w*|габарит\w*)(?:\s*\([^)]*\))?(?:,.*)?$', re.I)
FORK_DIMS = re.compile(r'габарит\w* вил(?:ки)?',re.I)
IGNORE = [r'^параметр$',r'^страна производства$',r'^тип привода$',r'^крепления$']

def clean(s):
    return s.casefold().replace('ё','е').strip()

def match(label):
    label=clean(label)
    if FORK_DIMS.search(label): return 'fork_dimensions'
    if DIMENSIONS.search(label): return 'dimensions'
    # Узкие правила до общих: скорость с грузом не превращается в общую.
    order=['loaded_speed','unloaded_speed','angular_accuracy','qr_precise_positioning']
    for key in order+list(k for k in ALIASES if k not in order):
        if any(re.search(p,label,re.I) for p in ALIASES[key]):return key
    return None
