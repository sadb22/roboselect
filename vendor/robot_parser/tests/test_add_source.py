import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from add_source import register
from parser import run
from web_pages import product_lines
ROOT=Path(__file__).resolve().parents[1]
URL='https://ronavi-robotics.ru/catalogue/h1500'

class URLIntake(unittest.TestCase):
    def test_one_url_fetch_registration_and_scoped_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('fields.json','scenarios.json'):(root/name).write_bytes((ROOT/name).read_bytes())
            (root/'sources.json').write_text(json.dumps({'sources':[]}))
            html=(ROOT/'tests/fixtures/ronavi_live_shape.html').read_bytes()
            source=register(URL,root,html_bytes=html)
            self.assertEqual(source['model_key'],'ronavi-h1500')
            self.assertEqual((root/source['path']).read_bytes(),html)
            summary=run(root,root/'out')
            self.assertEqual((summary['cards'],summary['offers'],summary['source_errors']),(1,2,0))
            offers=[json.loads(x) for x in (root/'out/offers.jsonl').read_text().splitlines()]
            self.assertEqual({x['price_min'] for x in offers},{'2160000'})
            self.assertTrue(all('99000000' not in json.dumps(x) for x in offers))
            again=register(URL,root,html_bytes=html)
            self.assertEqual(again['source_id'],source['source_id'])
            self.assertEqual(len(json.loads((root/'sources.json').read_text())['sources']),1)
    def test_unknown_domain_from_url_and_scoped_english_specs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('fields.json','scenarios.json'):(root/name).write_bytes((ROOT/name).read_bytes())
            (root/'sources.json').write_text(json.dumps({'sources':[]}))
            html=b'''<html><nav>Price: 99 000 000 USD</nav><main><h1>Atlas AMR-800</h1>
            <table><tr><th>Payload capacity</th><td>1 t</td></tr>
            <tr><th>Travel speed</th><td>3.6 km/h</td></tr>
            <tr><th>Runtime</th><td>up to 8 h</td></tr></table>
            <p>Price: 500000 USD</p><aside><p>Price: 100 USD</p></aside>
            <div class="related"><p>Payload capacity | 3000 kg</p></div></main></html>'''
            src=register('https://example.com/robots/amr-800',root,html_bytes=html)
            self.assertEqual(src['adapter'],'generic')
            self.assertEqual(src['model_key'],'example.com-amr-800')
            summary=run(root,root/'out')
            self.assertEqual((summary['cards'],summary['offers'],summary['source_errors']),(1,1,0))
            card=json.loads((root/'out/cards.jsonl').read_text().strip())
            self.assertEqual(card['fields']['payload']['value'],1000)
            self.assertEqual(card['fields']['travel_speed']['value'],1)
            self.assertEqual(card['fields']['runtime']['max'],8)
            offer=json.loads((root/'out/offers.jsonl').read_text().strip())
            self.assertEqual(offer['price_min'],'500000')
    def test_no_model_scope_becomes_review_issue(self):
        src={'source_id':'other','kind':'html','adapter':'generic','model_key':'robot-800','model_name':'Robot 800'}
        from parser import process_card,contract
        fields=contract(ROOT/'fields.json')[1]
        html='<h1>Robot 800</h1><table><tr><td>Payload</td><td>800 kg</td></tr></table>'
        obs,offers,issues,_=process_card(html,src,'snap',fields,'v')
        self.assertEqual((obs,offers),([],[]))
        self.assertTrue(any('Область модели не определена' in x['reason'] for x in issues))
    def test_jsonld_product_is_scoped_by_name(self):
        from parser import process_card,contract
        fields=contract(ROOT/'fields.json')[1]
        src={'source_id':'other','kind':'html','adapter':'generic','model_key':'robot-800','model_name':'Robot 800'}
        html='''<main><h1>Robot 800</h1><script type="application/ld+json">{"@type":"Product","name":"Robot 800","additionalProperty":[{"name":"Battery capacity","value":"20 Ah"}],"offers":{"price":"20000","priceCurrency":"EUR"}}</script><aside>Other robot</aside></main>'''
        obs,offers,issues,_=process_card(html,src,'snap',fields,'v')
        self.assertEqual(obs[0]['normalized']['value'],20000)
        self.assertEqual((len(offers),offers[0]['price_min']),(1,'20000'))
    def test_browser_fallback_for_js_rendered_specs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'sources.json').write_text('{"sources":[]}')
            static=b'<main><h1>Atlas AMR-800</h1><div id="app"></div></main>'
            rendered=b'<main><h1>Atlas AMR-800</h1><table><tr><th>Payload</th><td>800 kg</td></tr></table></main>'
            with patch('add_source.fetch_http',return_value=static),patch('add_source.fetch_browser',return_value=rendered) as browser:
                src=register('https://example.com/amr-800',root)
            browser.assert_called_once()
            self.assertEqual((root/src['path']).read_bytes(),rendered)
    def test_ambiguous_price_is_reviewed(self):
        from parser import process_card,contract
        fields=contract(ROOT/'fields.json')[1]
        src={'source_id':'s','kind':'html','adapter':'generic','model_key':'robot-800','model_name':'Robot 800'}
        html='<main><h1>Robot 800</h1><table><tr><td>Payload</td><td>800 kg</td></tr></table><p>Price: 100 USD</p><p>Price: 200 USD</p></main>'
        _,offers,issues,_=process_card(html,src,'snap',fields,'v')
        self.assertEqual(offers,[])
        self.assertTrue(any('Несколько цен' in x['reason'] for x in issues))
    def test_existing_txt_source_reuses_model_key_without_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);original={'source_id':'text-h1500','kind':'txt','path':'snapshots/manual.txt',
                'source_url':URL,'model_key':'ronavi-h1500','model_name':'Ronavi H1500','adapter':'ronavi'}
            (root/'sources.json').write_text(json.dumps({'sources':[original]}))
            html=(ROOT/'tests/fixtures/ronavi_live_shape.html').read_bytes()
            source=register(URL,root,html_bytes=html)
            all_sources=json.loads((root/'sources.json').read_text())['sources']
            self.assertEqual(len(all_sources),2)
            self.assertEqual(all_sources[0],original)
            self.assertEqual(source['model_key'],'ronavi-h1500')
    def test_other_known_page_sections(self):
        h2000='<h1>Ronavi H2000 — промышленный робот до 2 тонн</h1><h2>Технические характеристики</h2><p>Грузоподъемность | 2000 кг</p><h2>Нужны подробные спецификации?</h2><h3>Цена за единицу при покупке от 100 шт. Ronavi H2000: от 2 805 000 ₽</h3><p>Стоимость (2 805 000 — 3 300 000 ₽) зависит от оборудования.</p><p>Ronavi H1500: 99 000 000 ₽</p>'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'sources.json').write_text(json.dumps({'sources':[]}))
            source=register('https://ronavi-robotics.ru/catalogue/h2000',root,html_bytes=h2000.encode())
            self.assertEqual(source['model_key'],'ronavi-h2000')
        out,_=product_lines(h2000,{'source_url':'https://ronavi-robotics.ru/catalogue/h2000','adapter':'ronavi','model_name':'Ronavi H2000'})
        self.assertIn('Грузоподъемность | 2000 кг',out)
        self.assertIn('2 805 000 ₽',out)
        self.assertNotIn('99 000 000',out)
        moros='<h1>AMR800</h1><h2>Технические характеристики</h2><table><tr><td>Грузоподъемность</td><td>800 кг</td></tr></table><h2>Ключевые функциональные возможности</h2><p>Другой робот 500 кг</p>'
        out,_=product_lines(moros,{'source_url':'https://xn--l1aeahg.xn--p1ai/amr-800/','adapter':'moros','model_name':'AMR800'})
        self.assertIn('Грузоподъемность | 800 кг',out)
        self.assertNotIn('500 кг',out)
        robo='<h1>Geek+ M1000</h1><h2>Характеристики Geek+ M1000</h2><table><tr><td><div>Габариты (ДxШxВ), мм</div></td><td><div>1090x830x275</div></td></tr></table><h2>Обсуждения</h2><p>Другой робот 500 кг</p>'
        out,_=product_lines(robo,{'source_url':'https://robob2b.ru/catalog/mobilnye-roboty/transportnyy-amr-robot-geek-m1000/','adapter':'robob2b','model_name':'Geek+ M1000'})
        self.assertIn('Габариты (ДxШxВ), мм | 1090x830x275',out)
        self.assertNotIn('500 кг',out)

if __name__=='__main__':unittest.main()
