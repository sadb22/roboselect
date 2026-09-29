"""Минимальный проверяемый контракт интеграции для офлайн-выгрузки."""
import argparse, json
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCHEMA='1.1'
EXTRACTION={'parsed','ambiguous','error'}
REVIEW={'unreviewed','confirmed','rejected','conflict'}
PUBLICATION={'draft','published'}
SUPPORT={'claimed','verified','conditional','unsupported','needs_review'}

def read(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]

def validate(folder):
    tables={name:read(folder/(name+'.jsonl')) for name in
            ('cards','observations','offers','issues','snapshots','scenario_links')}
    def require(record,keys):
        missing=keys-record.keys()
        if missing:raise ValueError(f'Обязательные поля отсутствуют: {sorted(missing)}')
        if record['schema_version']!=SCHEMA:raise ValueError('Неизвестная версия схемы')
    snapshots={x['snapshot_id'] for x in tables['snapshots']}
    observations={x['observation_id'] for x in tables['observations']}
    seen=set()
    for card in tables['cards']:
        require(card,{'schema_version','model_key','fields','field_candidates','observation_ids','source_ids','review_state','publication_state'})
        if card['model_key'] in seen:raise ValueError('Модель повторена в cards')
        seen.add(card['model_key'])
        if card['review_state'] not in REVIEW or card['publication_state'] not in PUBLICATION:raise ValueError('Неверное состояние карточки')
        if not set(card['observation_ids'])<=observations:raise ValueError('Наблюдение карточки не найдено')
        for items in card['field_candidates'].values():
            for item in items:
                if not {'value','conditions','observation_ids'}<=item.keys():raise ValueError('Кандидат без доказательства')
                if not set(item['observation_ids'])<=observations:raise ValueError('Кандидат с неизвестным наблюдением')
    for obs in tables['observations']:
        require(obs,{'schema_version','observation_id','snapshot_id','field','raw_value','position','normalized','extraction_state','review_state'})
        if obs['snapshot_id'] not in snapshots:raise ValueError('Нет снимка наблюдения')
        if obs['extraction_state'] not in EXTRACTION or obs['review_state'] not in REVIEW:raise ValueError('Неверное состояние наблюдения')
    for offer in tables['offers']:
        require(offer,{'schema_version','offer_id','snapshot_id','transaction_type','tariff_period','price_kind','price_min','price_max','currency','raw_conditions','review_state'})
        if offer['snapshot_id'] not in snapshots or offer['review_state'] not in REVIEW:raise ValueError('Нет снимка/состояния предложения')
        if offer['transaction_type'] not in {'purchase','rental','service'}:raise ValueError('Неверный вид предложения')
        for key in ('price_min','price_max'):
            if offer[key] is not None:
                try:Decimal(offer[key])
                except (InvalidOperation,TypeError):raise ValueError('Цена не десятичная строка')
                if not isinstance(offer[key],str):raise ValueError('Цена должна быть строкой')
    for issue in tables['issues']:
        require(issue,{'schema_version','issue_id','review_state','lifecycle','reason'})
        if issue['review_state'] not in REVIEW or issue['lifecycle'] not in {'open','superseded','resolved'}:raise ValueError('Неверное состояние замечания')
    for link in tables['scenario_links']:
        require(link,{'schema_version','link_id','model_key','scenario_code','support_status','review_state','classification_source'})
        if link['support_status'] not in SUPPORT or link['review_state'] not in REVIEW:raise ValueError('Неверное состояние сценария')
    return {'valid':True,'cards':len(seen),'observations':len(observations),'offers':len(tables['offers']),'scenario_links':len(tables['scenario_links'])}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args()
    print(json.dumps(validate(a.folder),ensure_ascii=False))
