"""Офлайн-парсер. Непроверенные кандидаты и замечания; платформу и БД не изменяет."""
from __future__ import annotations
import argparse, csv, hashlib, json, re, shutil
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from collections import defaultdict
from normalize import normalize, dimensions, NormalizationError, compact, _family
from rules import match, VERSION as RULE_VERSION
from prices import parse as parse_price
from web_pages import product_lines, generic_product_lines

SCHEMA='1.1'
PARSER='3.3.0'
MANUAL={'catalog_status','catalog_class','trl','market_potential','industry','scenario'}
TYPES={'число','диапазон','текст','да/нет'}

def sid(*parts):return hashlib.sha256(json.dumps(parts,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
def stamp():return datetime.now(timezone.utc).isoformat()
def write(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
def load(path):
    if not path.exists():return []
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]

def contract(path):
    data=json.loads(path.read_text(encoding='utf-8'))
    if not data.get('schema_version') or not data.get('fields_version'):raise ValueError('Контракт без версии')
    keys=set()
    for f in data['fields']:
        if not all(k in f for k in ('key','label','type','unit','scope')):raise ValueError('Неполное поле')
        if f['key'] in keys:raise ValueError('Повтор ключа '+f['key'])
        if f['type'] not in TYPES:raise ValueError('Неизвестный тип '+f['type'])
        if f['type'] in ('число','диапазон') and f['unit'] in ('—',''):raise ValueError('Число без единицы '+f['key'])
        if f['type'] in ('число','диапазон') and f['key'] not in MANUAL|{'price_min','price_max'} and not _family(f['unit']):
            raise ValueError('Неподдерживаемая единица '+f['key'])
        keys.add(f['key'])
    required={'length','width','height','model','manufacturer','payload','runtime'}
    if not required<=keys:raise ValueError('Неполный контракт')
    return data,{f['key']:f for f in data['fields']}

class SectionParser(HTMLParser):
    """Проверенная разметка: article/section с data-model, равным выбранной модели."""
    def __init__(self,model):
        super().__init__();self.model=model.casefold();self.depth=0;self.capture=0;self.chunks=[];self.sections=[];self.muted=0
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    SILENT={'script','style','noscript'}
    def handle_starttag(self,tag,attrs):
        if tag in self.SILENT:self.muted+=1
        if tag in self.VOID:
            if self.capture and not self.muted and tag in ('br','hr'):self.chunks.append('\n')
            return
        self.depth+=1
        a=dict(attrs)
        if tag in ('article','section') and a.get('data-model','').casefold()==self.model and not self.capture:
            self.capture=self.depth;self.chunks=[]
        if self.capture and not self.muted and tag in ('tr','li','p','h2','h3'):self.chunks.append('\n')
        if self.capture and not self.muted and tag in ('td','th'):self.chunks.append(' | ')
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in self.VOID:return
        if tag in self.SILENT:self.muted=max(0,self.muted-1)
        if self.capture and self.depth==self.capture:
            self.sections.append(''.join(self.chunks));self.capture=0
        self.depth=max(0,self.depth-1)
    def handle_data(self,data):
        if self.capture and not self.muted:self.chunks.append(data)

def txt_entries(content):
    entries=[]
    for number,line in enumerate(content.splitlines(),1):
        line=compact(line)
        if not line or line.startswith(('##','---')):continue
        if '|' in line:
            label,value=line.split('|',1)
            entries.append((compact(label),compact(re.sub(r'^\s*\|','',value)),str(number)))
        elif ';' in line:
            # Сжатая карточка Ronavi: каждый заголовок перед точкой с запятой.
            bits=re.split(r'(?=(?:Габариты|Вес|Грузопод[ъь]емность|Тип навигации|Максимальная скорость передвижения|Вид беспроводной связи|Минимальная ширина проезда|Время автономной работы|Гарантия)\s*(?:\([^)]*\))?\s*;)',line,flags=re.I)
            for bit in bits:
                if ';' in bit:
                    a,b=bit.split(';',1);entries.append((compact(a),compact(b),str(number)))
        elif re.match(r'^цена\s+по запросу$',line,re.I):entries.append(('Цена','по запросу',str(number)))
    return entries

def process_card(content,source,snapshot,fields,version):
    model=source['model_key'];obs=[];offers=[];issues=[];unknown=[]
    def issue(reason,field=None,raw=None,position=None,kind='review'):
        i={'schema_version':SCHEMA,'issue_id':sid(snapshot,model,field,reason,position,version),
           'snapshot_id':snapshot,'source_id':source['source_id'],'model_key':model,'field':field,
           'reason':reason,'raw':raw,'position':position,'kind':kind,'review_state':'unreviewed','lifecycle':'open'}
        issues.append(i);return i
    def add(key,label,raw,pos,conditions=None,normalized=None):
        entry={'schema_version':SCHEMA,'observation_id':sid(snapshot,model,key,pos,raw,version),
               'snapshot_id':snapshot,'source_id':source['source_id'],'model_key':model,
               'field':key,'raw_label':label,'raw_value':raw,'position':pos,'conditions':conditions,
               'extraction_state':'parsed','review_state':'unreviewed','normalized':None}
        try:entry['normalized']=normalized if normalized is not None else normalize(fields[key],label,raw)
        except (NormalizationError,KeyError) as e:
            entry['extraction_state']='ambiguous';issue(str(e),key,raw,pos)
        obs.append(entry)
    kind=source['kind']
    section_label=None
    if kind=='html':
        parser=SectionParser(source['model_key']);parser.feed(content)
        if len(parser.sections)==1:
            content=parser.sections[0]
            section_label=f'[data-model="{model}"]'
        else:
            if source.get('adapter') in ('ronavi','moros','robob2b'):
                content,section_label=product_lines(content,source)
            else:
                content,section_label=generic_product_lines(content,source)
            if content is None:
                issue('Область модели не определена: '+section_label,kind='source');return obs,offers,issues,unknown
            if section_label=='generic:ambiguous-price':
                issue('Несколько цен в области модели: привязка предложения требует проверки','product_price_raw',kind='review')
    for label,raw,line in txt_entries(content):
        pos={'type':'line','line':int(line)} if kind=='txt' else {'type':'html_section','section':section_label,'rendered_line':int(line)}
        if re.search(r'^(?:цена(?:\s+(?:аренды|услуги|покупки))?|price|rental price)$',label,re.I):
            for ordinal,part in enumerate(raw.split(';')):
                offer,err=parse_price(label+' '+part,source['source_id'],model,source.get('supplier'),label+' '+raw)
                if err:issue(err,'product_price_raw',part,pos)
                elif offer:
                    offer.update(schema_version=SCHEMA,snapshot_id=snapshot,position=pos,
                                 offer_id=sid(snapshot,model,'price',pos,ordinal,part,version),extraction_state='parsed',review_state='unreviewed')
                    offers.append(offer)
                    if offer['requires_review']:issue('Условия цены/комплектации требуют подтверждения','product_price_raw',part,pos)
            continue
        key=match(label)
        if not key:
            # Отчёт включает каждую неизвестную метку, а не молча пропускает.
            if label not in ('Параметр','Ronavi H1500') and raw not in ('Значение',''):
                unknown.append({'source_id':source['source_id'],'snapshot_id':snapshot,'label':label,'raw':raw,'position':pos})
            continue
        if key=='dimensions':
            try:
                for k,v in dimensions(label,raw,fields).items():
                    add(k,label,raw,pos,normalized=v)
            except NormalizationError as e:issue(str(e),'length',raw,pos)
        elif key=='fork_dimensions':
            nums=re.split(r'\s*[×xх]\s*',raw,flags=re.I)
            if len(nums)!=4:issue('Для Д×Ш×В×Т нужны четыре компонента; исходная запись сохранена','fork_length',raw,pos)
            else:
                try:
                    for k,v in dimensions(label,raw,fields,('fork_length','fork_width','fork_height','fork_fourth_dimension')).items():
                        add(k,label,raw,pos,normalized=v)
                except NormalizationError as e:issue(str(e),'fork_length',raw,pos)
        elif key=='runtime' and len(re.findall(r'\d+\s*час',raw,re.I))>1:
            for m in re.finditer(r'([+-]?\d+(?:[,.]\d+)?)\s*час(?:а|ов)?\s*\(([^)]+)\)',raw,re.I):
                add(key,label,m.group(1)+' часов',pos,m.group(2))
            issue('Разные режимы работы: нет единого значения без условий',key,raw,pos)
        elif key=='operating_temperature' and re.match(r'\+?\d+\s*(?:-|–|—|до)\s*\+?\d+',raw):add(key,label,raw,pos)
        else:add(key,label,raw,pos)
    # Данные из регистра источника являются идентификацией, не извлечёнными ТТХ.
    return obs,offers,issues,unknown

def process_csv(data,source,snapshot,version):
    reader=csv.DictReader(data.splitlines(),delimiter=';')
    expected={'id','Название','компания','Цена изделия'}
    if not expected<=set(reader.fieldnames or []):raise ValueError('Неизвестный формат catalog_export_v4')
    rows=[];issues=[];suggestions=[]
    for number,row in enumerate(reader,2):
        if not row.get('id'):
            issues.append({'schema_version':SCHEMA,'issue_id':sid(snapshot,number,'empty-id',version),'snapshot_id':snapshot,
                           'source_id':source['source_id'],'field':'robot_id','position':{'type':'csv_row','line':number},
                           'reason':'Пустой ID каталога','review_state':'unreviewed','lifecycle':'open'})
        key=sid(snapshot,'catalog-row',number,version)
        rows.append({'schema_version':SCHEMA,'row_id':key,'snapshot_id':snapshot,'source_id':source['source_id'],
                     'catalog_id':row.get('id'),'position':{'type':'csv_row','line':number},'raw':row,
                     'extraction_state':'parsed','review_state':'unreviewed'})
        if re.search(r'\b(?:ronavi|ронави)\s*h[- ]?1500\b',row.get('Название',''),re.I):
            suggestions.append({'schema_version':SCHEMA,'suggestion_id':sid(snapshot,key,'ronavi-h1500',version),
                                'row_id':key,'catalog_id':row['id'],'model_key':'ronavi-h1500',
                                'evidence':{'name':row['Название'],'company':row.get('компания'),'sku':None,'configuration':None},
                                'review_state':'unreviewed','decision':'suggested_only'})
    return rows,issues,suggestions

def run(root,out,sources_path=None):
    cfg,fields=contract(root/'fields.json') # fail fast before any source
    scenario_path=root/'scenarios.json'
    scenario_cfg=json.loads(scenario_path.read_text(encoding='utf-8')) if scenario_path.exists() else {'scenarios':[]}
    scenarios={s['code']:s for s in scenario_cfg['scenarios']}
    source_list=json.loads((sources_path or root/'sources.json').read_text(encoding='utf-8'))['sources']
    out.mkdir(parents=True,exist_ok=True);(out/'snapshots').mkdir(exist_ok=True)
    version=PARSER+'+'+RULE_VERSION+'+'+cfg['fields_version']
    old={name:{x[idkey]:x for x in load(out/(name+'.jsonl'))} for name,idkey in
         [('observations','observation_id'),('offers','offer_id'),('issues','issue_id'),('catalog_rows','row_id'),('catalog_observations','observation_id'),('match_suggestions','suggestion_id'),('snapshots','snapshot_id')]}
    unknown=[];source_errors=[];processed=[]
    for index,source in enumerate(source_list):
        try:
            if not isinstance(source,dict):raise ValueError('Строка источника не объект')
            for required in ('source_id','kind','path','adapter'):
                if not isinstance(source.get(required),str) or not source[required]:raise ValueError('Не задано '+required)
            if source['kind'] not in ('txt','html','csv'):raise ValueError('Неподдерживаемый тип источника')
            for code in source.get('scenario_codes',[]):
                if code not in scenarios or scenarios[code]['category']!=source.get('category'):
                    raise ValueError('Некорректный код/категория сценария: '+code)
            path=(root/source['path']).resolve()
            if not path.is_relative_to(root.resolve()):raise ValueError('Путь вне пакета')
            raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest();snapshot=sid(source['source_id'],sha)
            target=out/'snapshots'/(sha+'.'+source['kind'])
            if not target.exists():target.write_bytes(raw)
            processed_at=stamp()
            previous=old['snapshots'].get(snapshot,{})
            runs=previous.get('processing_runs',{})
            runs.setdefault(version,processed_at)
            old['snapshots'][snapshot]={'schema_version':SCHEMA,'snapshot_id':snapshot,'source_id':source['source_id'],
                  'url_or_filename':source.get('source_url') or source['path'],'source_type':source['kind'],
                  'sha256':sha,'stored_path':target.relative_to(out).as_posix(),'acquired_at':source.get('acquired_at'),
                  'processed_at':runs[version],'parser_version':version,'processing_runs':runs}
            text=raw.decode('utf-8-sig')
            if source['kind']=='csv':
                rows,issues,suggestions=process_csv(text,source,snapshot,version)
                for x in rows:old['catalog_rows'][x['row_id']]=x
                for x in rows:
                    for column,value in x['raw'].items():
                        oid=sid(x['row_id'],column,version)
                        old['catalog_observations'][oid]={'schema_version':SCHEMA,'observation_id':oid,
                           'snapshot_id':snapshot,'source_id':source['source_id'],'catalog_id':x['catalog_id'],
                           'row_id':x['row_id'],'source_column':column,'raw_value':value,
                           'position':{'type':'csv_row','line':x['position']['line'],'column':column},
                           'extraction_state':'parsed','review_state':'unreviewed'}
                for x in suggestions:old['match_suggestions'][x['suggestion_id']]=x
                for x in issues:old['issues'][x['issue_id']]=x
            else:
                if not source.get('model_key') or not source.get('model_name'):raise ValueError('Нет идентификатора модели')
                obs,offers,issues,unrecognized=process_card(text,source,snapshot,fields,version)
                for x in obs:old['observations'][x['observation_id']]=x
                for x in offers:old['offers'][x['offer_id']]=x
                for x in issues:old['issues'][x['issue_id']]=x
                unknown+=unrecognized
            processed.append(source)
        except (OSError,ValueError,UnicodeError,TypeError,KeyError) as e:
            source_id=source.get('source_id',f'entry-{index}') if isinstance(source,dict) else f'entry-{index}'
            source_errors.append({'schema_version':SCHEMA,'source_id':source_id,'state':'source_unavailable' if isinstance(e,OSError) else 'error',
                                  'reason':str(e),'entry_index':index})
            iid=sid(source_id,index,str(e),version)
            old['issues'][iid]={'schema_version':SCHEMA,'issue_id':iid,'source_id':source_id,'snapshot_id':None,
                                'field':None,'reason':str(e),'kind':'source','review_state':'unreviewed','lifecycle':'open'}
    # Задача об отсутствовавшем поле заменяется появившимся наблюдением той же модели.
    have={(x['model_key'],x['field']) for x in old['observations'].values() if x['extraction_state']=='parsed'}
    for x in old['issues'].values():
        if x.get('reason')=='Нет в документе' and (x.get('model_key'),x.get('field')) in have:x['lifecycle']='superseded'
    bymodel=defaultdict(list)
    for x in old['observations'].values():bymodel[x['model_key']].append(x)
    cards=[];coverage=[];scenario_links=[]
    models=defaultdict(list)
    for source in processed:
        if source.get('model_key'):models[source['model_key']].append(source)
    for model,sources in models.items():
        source=sources[0]
        group=defaultdict(list)
        for x in bymodel[model]:group[x['field']].append(x)
        for required in ('payload','length','width','height','runtime'):
            iid=sid(model,required,'missing',version)
            if not group.get(required):
                old['issues'][iid]={'schema_version':SCHEMA,'issue_id':iid,'model_key':model,'field':required,
                    'reason':'Нет в документе','review_state':'unreviewed','lifecycle':'open'}
            elif iid in old['issues']:old['issues'][iid]['lifecycle']='superseded'
        resolved={};field_candidates={}
        for key,values in group.items():
            candidates=defaultdict(list)
            for x in values:
                if x['extraction_state']!='parsed':continue
                meaning={k:v for k,v in x['normalized'].items() if k!='source_unit'}
                candidates[(x.get('conditions'),json.dumps(meaning,ensure_ascii=False,sort_keys=True))].append(x)
            field_candidates[key]=[{'value':json.loads(serialized),'conditions':condition,
                                    'observation_ids':sorted(x['observation_id'] for x in items),
                                    'source_ids':sorted({x['source_id'] for x in items})}
                                   for (condition,serialized),items in sorted(candidates.items(),key=lambda pair:(str(pair[0][0]),pair[0][1]))]
            by_condition=defaultdict(set)
            for (condition,serialized) in candidates:by_condition[condition].add(serialized)
            conflicts={condition for condition,meanings in by_condition.items() if len(meanings)>1}
            if conflicts:
                for x in values:
                    if x.get('conditions') in conflicts:x['review_state']='conflict'
                iid=sid(model,key,'conflict',version)
                old['issues'][iid]={'schema_version':SCHEMA,'issue_id':iid,'model_key':model,'field':key,
                     'observation_ids':[v['observation_id'] for v in values if v.get('conditions') in conflicts],
                     'reason':'Противоречащие атомарные значения: до решения действующую запись не изменять',
                     'review_state':'conflict','lifecycle':'open'}
            if len(candidates)==1 and not conflicts:
                only=field_candidates[key][0]
                if only['conditions'] is None:resolved[key]=only['value']
            if not conflicts:
                stale=sid(model,key,'conflict',version)
                if stale in old['issues']:old['issues'][stale]['lifecycle']='superseded'
        cards.append({'schema_version':SCHEMA,'model_key':model,'model':source['model_name'],
                      'manufacturer':source.get('manufacturer'),'catalog_id':None,
                      'source_ids':sorted({s['source_id'] for s in sources}|{x['source_id'] for x in bymodel[model]}),
                      'observation_ids':sorted({x['observation_id'] for x in bymodel[model]}),
                      'fields':resolved,'field_candidates':field_candidates,'extraction_state':'parsed' if resolved else 'ambiguous',
                      'review_state':'unreviewed','publication_state':'draft'})
        for s in sources:
            for code in s.get('scenario_codes',[]):
                link_id=sid(model,code,'manual-scenario')
                if not any(x['link_id']==link_id for x in scenario_links):
                    scenario_links.append({'schema_version':SCHEMA,'link_id':link_id,'model_key':model,
                        'scenario_code':code,'support_status':'claimed','review_state':'unreviewed',
                        'classification_source':'sources.json','source_id':s['source_id'],
                        'explanation':'Сценарий назначен вручную в реестре источников; применимость не проверена'})
        for key in fields:
            if key in MANUAL or key in ('robot_id','source_url','retrieved_at','raw_quote','verification_status','model','manufacturer','product_price_raw','price_min','price_max','currency'):continue
            state='parsed' if key in resolved else 'unrecognized' if key in group else ('not_applicable' if fields[key]['scope']=='Уборка' and all(s.get('category')=='warehouse' for s in sources) else 'not_in_document')
            coverage.append({'schema_version':SCHEMA,'model_key':model,'field':key,'state':state})
    for name,idkey in [('observations','observation_id'),('offers','offer_id'),('issues','issue_id'),('catalog_rows','row_id'),('catalog_observations','observation_id'),('match_suggestions','suggestion_id'),('snapshots','snapshot_id')]:
        write(out/(name+'.jsonl'),sorted(old[name].values(),key=lambda x:x[idkey]))
    write(out/'cards.jsonl',cards);write(out/'scenario_links.jsonl',scenario_links)
    write(out/'scenarios.jsonl',[{'schema_version':SCHEMA,**s} for s in scenarios.values()])
    write(out/'coverage.jsonl',coverage);write(out/'unknown_labels.jsonl',unknown);write(out/'source_errors.jsonl',source_errors)
    (out/'schema.json').write_text(json.dumps({'schema_version':SCHEMA,'fields_version':cfg['fields_version'],
      'parser_version':version,'records':{'cards':'fields are unverified canonical candidates; publication_state is draft',
      'observations':'atomic source facts, normalized and extraction/review states; raw quote and position',
      'offers':'Decimal amounts as strings, unknowns null, independent conditions',
      'scenario_links':'manually curated source registry classification, claimed/unreviewed; no automated suitability inference',
      'scenarios':'manual scenario dictionary and categories',
      'issues':'review tasks with lifecycle open/superseded',
      'catalog_rows':'every source row including repeated ID',
      'catalog_observations':'every original CSV cell with original ID, row and column',
      'match_suggestions':'manual identity reconciliation only',
      'snapshots':'immutable raw files, acquisition date independent from processing date',
      'coverage':'parsed / unrecognized / not_in_document; unsupported source in source_errors'}},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'cards':len(cards),'observations':len(old['observations']),'offers':len(old['offers']),
            'catalog_rows':len(old['catalog_rows']),'unique_catalog_ids':len({x['catalog_id'] for x in old['catalog_rows'].values()}),
            'issues':len(old['issues']),'source_errors':len(source_errors),'unknown_labels':len(unknown)}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='example_export');ap.add_argument('--sources')
    a=ap.parse_args();base=Path(__file__).resolve().parent
    print(json.dumps(run(base,Path(a.output).resolve(),Path(a.sources).resolve() if a.sources else None),ensure_ascii=False))
