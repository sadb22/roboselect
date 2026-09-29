import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from normalize import normalize, dimensions, NormalizationError
from prices import parse
from rules import match
from parser import contract, process_card, run, sid

ROOT=Path(__file__).resolve().parents[1]
CFG,FIELDS=contract(ROOT/'fields.json')

def norm(key,label,raw):return normalize(FIELDS[key],label,raw)

class Quantities(unittest.TestCase):
    def test_units_scalar_range_and_components(self):
        self.assertEqual(norm('payload','Грузоподъемность, т','1,5 т')['value'],1500)
        self.assertEqual(norm('travel_speed','Скорость','36 км/ч')['value'],10)
        self.assertEqual(norm('charging_time','Время заряда','90 минут')['value'],1.5)
        self.assertEqual(norm('battery_capacity','Емкость','30 А·ч')['value'],30000)
        self.assertEqual(norm('runtime','Время работы','60–120 минут')['max'],2)
        self.assertEqual(norm('length','Длина','1 м')['value'],1000)
        self.assertEqual(norm('width','Ширина','12 см')['value'],120)
        d=dimensions('Габариты (Д×Ш×В)','940 × 640 × 230 мм',FIELDS)
        self.assertEqual([d[k]['value'] for k in ('length','width','height')],[940,640,230])
        d=dimensions('Габариты (Д×Ш×В)','0,94 м x 64 см х 230 мм',FIELDS)
        self.assertEqual([d[k]['value'] for k in ('length','width','height')],[940,640,230])
    def test_qualifiers_and_semantics(self):
        self.assertEqual(norm('runtime','Время работы','до 10 ч')['min'],None)
        self.assertEqual(norm('runtime','Время работы','до 10 ч')['max'],10)
        self.assertEqual(norm('payload','Грузоподъемность','от 1,5 т')['qualifier'],'lower_bound')
        self.assertEqual(norm('operating_temperature','Рабочая температура, °C','-10 — +40')['min'],-10)
        for k,l,v in [('payload','Грузоподъемность','-10 кг'),('length','Длина','-1 м'),('runtime','Время','14–12 ч'),('battery_life','Ресурс','1,5 циклов'),('length','Длина, мм','10 см'),('length','Длина','10 ft')]:
            with self.subTest(k=k,v=v),self.assertRaises(NormalizationError):norm(k,l,v)
        self.assertNotEqual(match('Кнопка аварийной остановки'),None)
        self.assertEqual(match('Кнопки аварийной остановки'),'emergency_buttons')
        self.assertEqual(match('Кнопок аварийной остановки'),'emergency_buttons')
        with self.assertRaises(NormalizationError):norm('emergency_buttons','Кнопка аварийной остановки','да')
        with self.assertRaises(NormalizationError):norm('shelf_recognition','Распознавание полок','Опционально')
    def test_price(self):
        for s,expected in [('Цена 2 700 000 руб.','2700000'),('ЦЕНА 2700000 руб.','2700000'),('Цена 2\u00a0700\u00a0000,50 ₽','2700000.50')]:
            o,e=parse(s,'s','m');self.assertIsNone(e);self.assertEqual(o['price_min'],expected)
        o,e=parse('Цена от 2 160 000 ₽ при покупке от 100 шт.','s','m')
        self.assertEqual((o['price_kind'],o['minimum_quantity'],o['price_min']),('lower_bound',100,'2160000'))
        o,e=parse('Цена по запросу','s','m');self.assertEqual(o['price_kind'],'unknown');self.assertIsNone(o['price_min'])
        o,e=parse('Цена 2 160 000 — 2 700 000 ₽','s','m');self.assertEqual((o['price_min'],o['price_max']),('2160000','2700000'))

class Pipeline(unittest.TestCase):
    def test_catalog_and_idempotence(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'export';a=run(ROOT,out);b=run(ROOT,out)
            self.assertEqual((a['catalog_rows'],a['unique_catalog_ids']),(223,187))
            for key in ('cards','observations','offers','issues','catalog_rows'):
                self.assertEqual(a[key],b[key])
            rows=[json.loads(s) for s in (out/'catalog_rows.jsonl').read_text().splitlines()]
            byid=[x for x in rows if x['catalog_id']=='5760e938-9a43-45a7-b8e8-f4f2e6383930']
            self.assertEqual(len(byid),2);self.assertNotEqual(byid[0]['row_id'],byid[1]['row_id'])
            snapshots=[json.loads(s) for s in (out/'snapshots.jsonl').read_text().splitlines()]
            self.assertTrue(all(s['acquired_at'] is None for s in snapshots))
            self.assertTrue(all((out/s['stored_path']).exists() for s in snapshots))
    def test_scoped_price_and_conflict(self):
        src={'source_id':'s','kind':'html','adapter':'ronavi','model_key':'ronavi-h1500','model_name':'H1500'}
        html='<article data-model="ronavi-h1500"><p>Грузоподъемность | до 1500 кг</p><p>Цена | 2700000 руб.</p></article><article data-model="other"><p>Цена | 99 000 000 руб.</p></article>'
        o,p,i,u=process_card(html,src,'snap',FIELDS,'v')
        self.assertEqual(len(p),1);self.assertEqual(p[0]['price_min'],'2700000')
        src['adapter']='unknown';self.assertEqual(len(process_card(html,src,'snap',FIELDS,'v')[1]),1)
        src['adapter']='ronavi';src['kind']='txt'
        x=process_card('Время работы | до 10 ч\nВремя работы | 12–14 ч',src,'s2',FIELDS,'v')[0]
        self.assertEqual((x[0]['normalized']['min'],x[0]['normalized']['max']),(None,10))
        self.assertEqual((x[1]['normalized']['min'],x[1]['normalized']['max']),(12,14))
    def test_bad_source_continues(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'sources.json';cfg=json.loads((ROOT/'sources.json').read_text());cfg['sources'].insert(0,{'broken':1});p.write_text(json.dumps(cfg))
            summary=run(ROOT,Path(d)/'out',p)
            self.assertEqual((summary['source_errors'],summary['cards']),(1,5))
    def test_atomic_conflict_and_superseded_missing_issue(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'package';root.mkdir()
            (root/'fields.json').write_bytes((ROOT/'fields.json').read_bytes())
            src={'source_id':'one','kind':'txt','path':'one.txt','adapter':'ronavi','model_key':'m','model_name':'M','acquired_at':None}
            (root/'one.txt').write_text('Время работы | до 10 ч\nГрузоподъемность | 100 кг',encoding='utf-8')
            (root/'sources.json').write_text(json.dumps({'sources':[src]}))
            out=Path(d)/'out';run(root,out)
            before=[json.loads(s) for s in (out/'issues.jsonl').read_text().splitlines()]
            self.assertTrue(any(x['field']=='length' and x['lifecycle']=='open' for x in before))
            (root/'one.txt').write_text('Время работы | 12–14 ч\nГрузоподъемность | 100 кг\nДлина | 1000 мм',encoding='utf-8')
            run(root,out)
            issues=[json.loads(s) for s in (out/'issues.jsonl').read_text().splitlines()]
            self.assertTrue(any(x['field']=='length' and x['lifecycle']=='superseded' for x in issues))
            self.assertTrue(any(x['field']=='runtime' and x['review_state']=='conflict' for x in issues))
            cards=[json.loads(s) for s in (out/'cards.jsonl').read_text().splitlines()]
            self.assertNotIn('runtime',cards[0]['fields'])
            observations=[json.loads(s) for s in (out/'observations.jsonl').read_text().splitlines()]
            self.assertEqual(len([x for x in observations if x['field']=='runtime']),2)
    def test_contract_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fields.json';x=json.loads((ROOT/'fields.json').read_text());x['fields'].append(x['fields'][0]);p.write_text(json.dumps(x))
            with self.assertRaisesRegex(ValueError,'Повтор ключа'):contract(p)

if __name__=='__main__':unittest.main()
