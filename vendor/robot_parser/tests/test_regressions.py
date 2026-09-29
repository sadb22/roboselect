import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from normalize import normalize, NormalizationError
from prices import parse
from parser import run, process_card, contract
from validate_export import validate
ROOT=Path(__file__).resolve().parents[1]
FIELDS=contract(ROOT/'fields.json')[1]

def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]

class P1Regressions(unittest.TestCase):
    def test_unicode_minus_unknown_unit_and_no_partial_number(self):
        for label,value in [('Грузоподъёмность','−100 кг'),('Грузоподъёмность, кг','100 lb'),('Грузоподъёмность, кг','100 кг lb'),('Грузоподъёмность','1e3 кг'),('Грузоподъёмность, кг','100 мм²')]:
            with self.subTest(value=value),self.assertRaises(NormalizationError):
                normalize(FIELDS['payload'],label,value)
        n=normalize(FIELDS['operating_temperature'],'Температура','−10…+40 °C')
        self.assertEqual((n['min'],n['max']),(-10,40))
    def test_rental_usd_negative_and_complete_conditions(self):
        rent,error=parse('Цена аренды 100000 руб./месяц','s','m')
        self.assertIsNone(error);self.assertEqual((rent['transaction_type'],rent['tariff_period']),('rental','месяц'))
        self.assertNotEqual(rent['transaction_type'],'purchase')
        usd,error=parse('Цена 500 USD','s','m')
        self.assertIsNone(error);self.assertEqual((usd['currency'],usd['price_min']),('USD','500'))
        self.assertIsNone(parse('Цена -1000 руб.','s','m')[0])
        full='Цена от 2160000 ₽ при покупке от 100 шт.; диапазон 2160000 — 2700000 ₽ с НДС 20%'
        first,error=parse('Цена '+full.split(';')[0][5:],'s','m',full_text=full)
        self.assertIsNone(error);self.assertEqual(first['minimum_quantity'],100)
        self.assertEqual(first['raw_conditions'],full)
        src={'source_id':'rental','kind':'txt','adapter':'ronavi','model_key':'m','model_name':'M'}
        _,offers,issues,_=process_card('Цена аренды | 100000 руб./месяц',src,'snap',FIELDS,'v')
        self.assertEqual(len(offers),1)
        self.assertEqual((offers[0]['transaction_type'],offers[0]['tariff_period']),('rental','месяц'))
        self.assertEqual(issues,[])
    def test_html_void_and_hidden_script(self):
        html=(ROOT/'tests/fixtures/scoped_card.html').read_text()
        src={'source_id':'html','kind':'html','adapter':'ronavi','model_key':'m','model_name':'M'}
        observations,offers,issues,_=process_card(html,src,'s',FIELDS,'v')
        self.assertEqual(len(offers),1)
        self.assertEqual((offers[0]['currency'],offers[0]['price_min']),('USD','500'))
        self.assertTrue(any(x['field']=='length' and x['normalized']['value']==1000 for x in observations))
        self.assertFalse(any('Область модели' in x['reason'] for x in issues))
    def test_semantic_merge_one_card_and_scenarios(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'p';base.mkdir()
            (base/'fields.json').write_bytes((ROOT/'fields.json').read_bytes())
            (base/'scenarios.json').write_bytes((ROOT/'scenarios.json').read_bytes())
            a={'source_id':'a','kind':'txt','path':'a.txt','adapter':'ronavi','model_key':'m','model_name':'M','category':'warehouse','scenario_codes':['warehouse_general_transport']}
            b=dict(a,source_id='b',path='b.txt')
            (base/'sources.json').write_text(json.dumps({'sources':[a,b]}))
            (base/'a.txt').write_text('Длина | 1000 мм\nВремя работы | до 10 ч')
            (base/'b.txt').write_text('Длина | 1 м\nВремя работы | до 10 ч')
            out=Path(d)/'out';first=run(base,out);second=run(base,out)
            self.assertEqual((first['cards'],first['issues']),(1,3)) # missing payload, width, height
            self.assertEqual(first,second)
            card=rows(out/'cards.jsonl')[0]
            self.assertEqual(card['source_ids'],['a','b'])
            self.assertEqual(card['fields']['length']['value'],1000)
            self.assertEqual(len(card['field_candidates']['length'][0]['observation_ids']),2)
            self.assertFalse(any(x.get('review_state')=='conflict' for x in rows(out/'issues.jsonl')))
            links=rows(out/'scenario_links.jsonl')
            self.assertEqual(len(links),1);self.assertEqual(links[0]['support_status'],'claimed')
            self.assertEqual(links[0]['review_state'],'unreviewed')
            self.assertTrue(validate(out)['valid'])
            cards=rows(out/'cards.jsonl')
            cards[0]['publication_state']='unexpected'
            (out/'cards.jsonl').write_text(json.dumps(cards[0])+'\n')
            with self.assertRaisesRegex(ValueError,'Неверное состояние'):validate(out)

if __name__=='__main__':unittest.main()
