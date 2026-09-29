"""Словарь меток: добавлять алиасы здесь, не меняя pipeline."""
import re

VERSION = '2026-09-29-v4-en'
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
EN_ALIASES={
 'length':[r'^length(?:\s*[,(:].*)?$'],
 'width':[r'^width(?:\s*[,(:].*)?$'],
 'height':[r'^height(?:\s*[,(:].*)?$'],
 'robot_mass':[r'^(?:robot\s+)?(?:weight|mass)(?:\s*[,(:].*)?$'],
 'payload':[r'\b(?:payload(?:\s+capacity)?|load\s+capacity|carrying\s+capacity|maximum\s+load)\b'],
 'loaded_speed':[r'\b(?:speed\s+(?:with|under)\s+load|loaded\s+speed)\b'],
 'unloaded_speed':[r'\b(?:speed\s+without\s+load|unloaded\s+speed)\b'],
 'travel_speed':[r'\b(?:travel\s+speed|maximum\s+speed|max\.?\s+speed|moving\s+speed)\b'],
 'lift_height':[r'\b(?:lift(?:ing)?\s+height|fork\s+lift\s+height)\b'],
 'turning_diameter':[r'\bturning\s+diameter\b'],
 'max_grade':[r'\b(?:gradeability|maximum\s+gradient|slope\s+capacity)\b'],
 'navigation_type':[r'\b(?:navigation(?:\s+(?:type|method|system))?|guidance\s+system)\b'],
 'positioning_accuracy':[r'\b(?:positioning|localization)\s+accuracy\b'],
 'angular_accuracy':[r'\bangular\s+accuracy\b'],
 'battery_capacity':[r'\bbattery\s+capacity\b'],
 'battery_voltage':[r'\bbattery\s+voltage\b'],
 'battery_chemistry':[r'\bbattery\s+(?:type|chemistry)\b'],
 'runtime':[r'\b(?:runtime|run\s*time|operating\s*time|working\s+time|battery\s+life\s+per\s+charge)\b'],
 'charging_time':[r'\b(?:charging|charge)\s+time\b'],
 'operating_temperature':[r'\b(?:operating|working)\s+temperature\b'],
 'min_aisle_width':[r'\bminimum\s+aisle\s+width\b'],
 'fork_width':[r'\bfork\s+width\b'],
 'fork_length':[r'\bfork\s+length\b'],
 'emergency_buttons':[r'\bemergency\s+stop\s+buttons?\b'],
 'ip_rating':[r'\b(?:ip\s+rating|ingress\s+protection)\b'],
 'cleaning_width':[r'\b(?:cleaning|scrubbing)\s+width\b'],
 'cleaning_productivity':[r'\b(?:cleaning\s+productivity|cleaning\s+capacity|area\s+coverage)\b'],
 'clean_water_tank':[r'\b(?:clean|fresh|solution)\s+water\s+tank\b'],
 'dirty_water_tank':[r'\b(?:dirty|waste|recovery)\s+water\s+tank\b'],
 'noise_level':[r'\bnoise\s+level\b'],
}
for key,patterns in EN_ALIASES.items():ALIASES.setdefault(key,[]).extend(patterns)
DIMENSIONS = re.compile(r'^(?:габаритн\w* размер\w*|габарит\w*|(?:overall\s+)?dimensions?)(?:\s*\([^)]*\))?(?:,.*)?$', re.I)
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
