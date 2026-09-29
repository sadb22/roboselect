"""Единицы и значения. Один входной фрагмент -> одно атомарное значение либо ошибка."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

NUMBER = re.compile(r"(?<![\w.,])[-+]?\d+(?:[\s\u00a0\u202f]\d{3})*(?:[.,]\d+)?(?![\d.,])")
RANGE_SEPARATOR = re.compile(r"(?<=\d)\s*[-–—]\s*(?=[+-]?\d)")
SIGNS = str.maketrans({'−':'-','﹣':'-','－':'-','＋':'+'})
UNIT_TOKEN = re.compile(
    r'(?:мм|см|м|м/[сc](?:2)?|км/ч|кг|т|тонн(?:а|ы)?|mm|cm|km/h|m/s(?:2)?|kg|t|tons?|tonnes?|'
    r'час(?:ов|а)?|ч|мин(?:ута|уты|ут)?\.?|месяц(?:ев|а|ы)?|год(?:а|ов)?|лет|hours?|hrs?|h|minutes?|mins?|months?|years?|yrs?|'
    r'а\*?ч|ма\*?ч|квт\*?ч|м2/ч|операц(?:ий|ии)/ч|ah|mah|kwh|m2/h|'
    r'°[cс]|°|град(?:усов|уса|\.)?|в|вольт(?:а|ов)?|volts?|v|'
    r'цикл(?:ов|а)?|шт\.?|л|литр(?:а|ов)?|дб(?:\(а\))?|pcs?|cycles?|liters?|litres?|db(?:\(a\))?)', re.I)
COUNT_KEYS = {"drive_wheels","battery_life","emergency_buttons"}
NONNEGATIVE = {"robot_mass","payload","towing_capacity","battery_capacity","battery_voltage","battery_life","charging_time","runtime","electricity_consumption","operations_per_hour","cleaning_productivity","noise_level","travel_speed","loaded_speed","unloaded_speed","positioning_accuracy","angular_accuracy","emergency_buttons"}
POSITIVE_UNIT_KEYS = {"length","width","height","turning_diameter","min_aisle_width","obstacle_height","fork_length","fork_width","fork_height","fork_fourth_dimension","load_center","lift_height","load_length","load_width","load_height","cleaning_width","clean_water_tank","dirty_water_tank","dust_tank"}


class NormalizationError(ValueError):
    pass


def compact(s: str) -> str:
    return " ".join(str(s).replace("\u00a0"," ").replace("\u202f"," ").split())


def _word(s: str) -> str:
    return compact(s).casefold().replace("ё","е")


def unit_candidates(s: str) -> set[str]:
    s=_word(s).replace("·","*").replace("²","2")
    found=set()
    # Более длинные единицы проверяем первыми; их фрагменты не читаем второй раз.
    rules=[
        ("kmh",r"км\s*/\s*ч|км\s*в\s*час|\bkm\s*/\s*h\b"),
        ("mps2",r"м\s*/\s*с\s*2|\bm\s*/\s*s\s*2\b"),
        ("mps",r"м\s*/\s*[сc](?!\s*2)|\bm\s*/\s*s(?!\s*2)"),
        ("mAh",r"м\s*а\s*\*?\s*ч|\bmah\b"),
        ("Ah",r"(?<![а-яa-z])а\s*\*?\s*ч|\bah\b"),
        ("kWh",r"квт\s*\*?\s*ч|\bkwh\b"),
        ("m2h",r"м\s*2\s*/\s*ч|\bm\s*2\s*/\s*h\b"),
        ("ops_h",r"операц(?:ий|ии)\s*/\s*ч"),
        ("hours",r"\b(?:час(?:ов|а)?|ч|hours?|hrs?|h)\b"),
        ("minutes",r"\b(?:минут(?:а|ы)?|мин|minutes?|mins?)\.?\b"),
        ("months",r"\b(?:месяц(?:ев|а|ы)?|months?)\b"),
        ("years",r"\b(?:год(?:а|ов)?|лет|years?|yrs?)\b"),
        ("mm",r"\b(?:мм|mm)\b"),
        ("cm",r"\b(?:см|cm)\b"),
        ("meters",r"(?<![а-яa-z])м(?![а-яa-z])|\bmeters?\b|\bmetres?\b|\bm\b"),
        ("kg",r"\b(?:кг|kg)\b"),
        ("tonnes",r"\b(?:тонн(?:а|ы)?|т|t|tonnes?|tons?)\b"),
        ("degC",r"°\s*c|градус(?:ов|а)?\s*цельси"),
        ("degrees",r"(?:°|град(?:усов|уса|\.)?)"),
        ("volts",r"(?<![а-яa-z])в(?![а-яa-z])|\bвольт(?:а|ов)?\b|\bvolts?\b|\bv\b"),
        ("cycles",r"\b(?:цикл(?:ов|а)?|cycles?)\b"),
        ("pieces",r"\b(?:шт\.?|pcs?)\b"),
        ("liters",r"\b(?:л|литр(?:а|ов)?|liters?|litres?)\b"),
        ("db",r"\b(?:дб|db)(?:\([аa]\))?\b"),
    ]
    for unit,pattern in rules:
        if re.search(pattern,s):found.add(unit)
    # Удаление известных составных величин из подстроки предотвращает чтение
    # их компонентов («м/с» как метр, «мА·ч» как час и т. п.).
    if found & {"kmh","mps","mps2","mAh","Ah","kWh","m2h","ops_h"}:
        found-={"meters","hours"}
    if "degC" in found:found.discard("degrees")
    if "mm" in found or "cm" in found:found.discard("meters")
    return found


def _family(target: str):
    if target=="мм":return {"mm":Decimal(1),"cm":Decimal(10),"meters":Decimal(1000)}
    if target=="м/с":return {"mps":Decimal(1),"kmh":Decimal(1)/Decimal('3.6')}
    if target=="кг":return {"kg":Decimal(1),"tonnes":Decimal(1000)}
    if target=="ч":return {"hours":Decimal(1),"minutes":Decimal(1)/Decimal(60)}
    if target=="мА·ч":return {"mAh":Decimal(1),"Ah":Decimal(1000)}
    if target=="мес":return {"months":Decimal(1),"years":Decimal(12)}
    if target=="°C":return {"degC":Decimal(1)}
    if target=="°":return {"degrees":Decimal(1)}
    if target=="В":return {"volts":Decimal(1)}
    if target=="кВт·ч":return {"kWh":Decimal(1)}
    if target=="м/с²":return {"mps2":Decimal(1)}
    if target=="м²/ч":return {"m2h":Decimal(1)}
    if target=="операций/ч":return {"ops_h":Decimal(1)}
    if target=="шт.":return {"pieces":Decimal(1)}
    if target=="циклов":return {"cycles":Decimal(1)}
    if target=="л":return {"liters":Decimal(1)}
    if target=="дБ(А)":return {"db":Decimal(1)}
    if target=="IP":return {"ip":Decimal(1)}
    if target in ("—","",None):return {}
    return {}


def choose_unit(label: str, raw: str, target: str, key: str) -> tuple[str,Decimal]:
    if target=="IP":
        if not re.search(r"\bIP\s*\d+",label+" "+raw,re.I):raise NormalizationError("Нет числового класса IP")
        return "IP",Decimal(1)
    family=_family(target)
    if not family:raise NormalizationError("Единица поля не поддержана: "+str(target))
    # Числа внутри условий 80–20% не считаются единицами автономности.
    la=unit_candidates(re.sub(r"\([^)]*%[^)]*\)","",label))
    ra=unit_candidates(raw)
    known=set().union(*[set(_family(t)) for t in ("мм","м/с","кг","ч","мА·ч","мес","°C","°","В","кВт·ч","м²/ч","м/с²","л","шт.","циклов","дБ(А)")])
    la &= known
    ra &= known
    # Для °C одиночный «°» в той же записи — часть температуры.
    if "degC" in la:la.discard("degrees")
    if "degC" in ra:ra.discard("degrees")
    if len(la)>1 or len(ra)>1:raise NormalizationError("Несколько единиц в одном поле")
    a=next(iter(la),None);b=next(iter(ra),None)
    if a and b and a!=b:raise NormalizationError(f"Противоречие единиц: заголовок {a}, значение {b}")
    # Проверяем суффикс каждой величины, даже если в заголовке есть известная
    # единица: «100 lb» не может унаследовать «кг» от заголовка.
    for m in NUMBER.finditer(raw.translate(SIGNS)):
        tail=raw.translate(SIGNS)[m.end():]
        suffix=re.match(r"\s*([A-Za-zА-Яа-я°][A-Za-zА-Яа-я0-9°²/*·.]*)(?!\w)",tail)
        if suffix and suffix.group(1).casefold().replace('ё','е') not in ('до','от','при','to','up','min','max'):
            token=suffix.group(1).casefold().replace('ё','е').replace('·','*').replace('²','2')
            if not UNIT_TOKEN.fullmatch(token) or not unit_candidates(suffix.group(1)):
                raise NormalizationError("Неизвестная единица измерения: "+suffix.group(1))
            remainder=tail[suffix.end():].strip()
            if re.match(r"^[A-Za-zА-Яа-я]",remainder):
                raise NormalizationError("Лишний текст после единицы: "+remainder)
    unit=b or a
    if unit is None:
        if target in ("шт.","циклов") and key in COUNT_KEYS:return target,Decimal(1)
        raise NormalizationError("Единица измерения не указана")
    if unit not in family:raise NormalizationError("Единица не подходит полю: "+unit)
    return unit,family[unit]


def numeric_parts(raw: str) -> list[Decimal]:
    s=RANGE_SEPARATOR.sub(" TO ",compact(raw).translate(SIGNS))
    if re.search(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?[eE][+-]?\d+",s):
        raise NormalizationError("Научная запись числа не поддержана")
    if re.search(r"(?<!\w)[+-]?\d+[.,]\d+[.,]\d+|[+\-]{2,}\d",s):
        raise NormalizationError("Неподдерживаемая запись числа")
    out=[]
    for m in NUMBER.finditer(s):
        if (m.end()<len(s) and re.match(r"[A-Za-zА-Яа-я0-9.,]",s[m.end()])) or (m.start()>0 and re.match(r"[A-Za-zА-Яа-я0-9]",s[m.start()-1])):
            raise NormalizationError("Число прочитано не полностью")
        value=m.group().replace(" ","").replace("\u00a0","").replace("\u202f","").replace(",",".")
        try:d=Decimal(value)
        except InvalidOperation as e:raise NormalizationError("Нечитаемое число") from e
        if not d.is_finite():raise NormalizationError("Неконечное число")
        out.append(d)
    return out


def json_number(d: Decimal):
    if not d.is_finite():raise NormalizationError("Неконечное число")
    return int(d) if d==d.to_integral_value() else float(d)


def _qualifier(label: str,raw: str) -> str | None:
    text=_word(label+" "+raw)
    if "±" in text:return "plus_minus"
    if re.search(r"\b(?:не более|до|up to|at most|no more than)\b",_word(raw)):return "upper_bound"
    if re.search(r"\b(?:не менее|от|at least|from)\b",_word(raw)):return "lower_bound"
    if "максимальн" in text or re.search(r'\b(?:maximum|max\.)\b',text):return "maximum"
    return None


def normalize(field: dict,label: str,raw: str) -> dict:
    key,kind,target=field['key'],field['type'],field['unit']
    if kind=='текст':return {'value':compact(raw),'unit':None,'qualifier':None}
    if kind=='да/нет':
        val=_word(raw)
        if val in ('да','есть','поддерживается','yes','true','supported'):return {'value':True,'unit':None,'qualifier':None}
        if val in ('нет','отсутствует','не поддерживается','no','false','unsupported'):return {'value':False,'unit':None,'qualifier':None}
        raise NormalizationError("Неоднозначная опция/условие вместо да или нет")
    if key=='ip_rating':
        if 'по желанию' in _word(raw) or 'опциональн' in _word(raw):raise NormalizationError("Защита указана как опция")
        m=re.search(r"\bIP\s*(\d+)\b",label+" "+raw,re.I)
        if not m:raise NormalizationError("Класс IP не распознан")
        return {'value':int(m.group(1)),'unit':'IP','qualifier':_qualifier(label,raw)}
    unit,factor=choose_unit(label,raw,target,key)
    nums=numeric_parts(raw)
    if not nums:raise NormalizationError("Число отсутствует")
    if len(nums)>2 or (len(nums)>1 and kind!='диапазон'):
        raise NormalizationError("Несколько чисел/условий требуют отдельной проверки")
    vals=[n*factor for n in nums]
    if key in POSITIVE_UNIT_KEYS and any(v<=0 for v in vals):raise NormalizationError("Размер/объём должен быть положительным")
    if key in NONNEGATIVE and any(v<0 for v in vals):raise NormalizationError("Отрицательное значение не имеет смысла для этого поля")
    if key in COUNT_KEYS and any(v!=v.to_integral_value() for v in vals):raise NormalizationError("Счётчик должен быть целым")
    qual=_qualifier(label,raw)
    if kind=='число':
        return {'value':json_number(vals[0]),'unit':target,'qualifier':qual,'source_unit':unit}
    if len(vals)==2:
        lo,hi=vals
        if lo>hi:raise NormalizationError("Нижняя граница выше верхней")
    else:
        if qual=='upper_bound':lo,hi=None,vals[0]
        elif qual=='lower_bound':lo,hi=vals[0],None
        else:lo=hi=vals[0]
    return {'min':json_number(lo) if lo is not None else None,
            'max':json_number(hi) if hi is not None else None,
            'unit':target,'qualifier':qual,'source_unit':unit}


def dimensions(label: str,raw: str,field_by_key: dict,keys=('length','width','height')) -> dict:
    parts=re.split(r"\s*[×xх]\s*",raw,flags=re.I)
    if len(parts)!=len(keys):raise NormalizationError("Число компонентов габаритов не совпало с Д×Ш×В")
    # Единица может быть общей в конце или только в заголовке. Используем её
    # для каждого компонента, проверив отсутствие конфликтующих единиц внутри.
    all_units=unit_candidates(raw)
    if len(all_units)>1 and not all(unit_candidates(p) for p in parts):
        raise NormalizationError("Часть компонентов без единицы при смешанных единицах")
    shared=next(iter(all_units),None)
    suffixes={'mm':'мм','cm':'см','meters':'м'}
    out={}
    for i,(key,part) in enumerate(zip(keys,parts)):
        suffix='' if unit_candidates(part) else (' '+suffixes[shared] if shared in suffixes else '')
        clean_label=re.sub(r'\([^)]*[Дд][×xх][Шш][×xх][Вв][^)]*\)','',label)
        out[key]=normalize(field_by_key[key],clean_label,part+suffix)
    return out
