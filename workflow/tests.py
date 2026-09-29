import csv
import io
from copy import deepcopy
from datetime import timedelta
from django.test import TestCase,Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from .models import *
from .demo import seed
from .domain import default_requirements,requirements
from .finance import defaults,calculate
from .views import catalog_snapshot
from .selection import evaluate,suggest
from .catalog import submit,publish,import_csv,TEMPLATE

class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=get_user_model().objects.create_user('admin',password='TestingPassword123!',is_staff=True)
        cls.customer=get_user_model().objects.create_user('customer',password='TestingPassword123!')
        cls.other=get_user_model().objects.create_user('other',password='TestingPassword123!')
        seed(cls.admin)

    def setup_config(self):
        self.client.force_login(self.customer)
        study=Study.objects.create(owner=self.customer,name='Test warehouse')
        version=StudyVersion.objects.create(study=study,number=1,requirements=default_requirements(),finance=defaults())
        snap=catalog_snapshot();results,_=suggest(version.requirements,version.finance,snap)
        assignments,result=results[0]
        config=Configuration.objects.create(version=version,assignments=assignments,snapshot={str(a['revision']):snap[a['revision']] for a in assignments},result=result)
        return config

    def test_finance_matches_corrected_workbook(self):
        data=dict(power_kw=.4,purchase=3000000,rental_month=110000)
        groups=[dict(id='fleet',kind='robot',count=17,total_count=19,data=data)]
        rows={x['mode']:x for x in calculate(defaults(),groups,250*8*247)}
        self.assertEqual(rows['baseline']['tco'],'204000000.00')
        self.assertEqual(rows['purchase']['tco'],'145885792.00')
        self.assertEqual(rows['rental']['tco'],'175575792.00')
        self.assertEqual(rows['purchase']['npv'],'13501802.12')
        self.assertEqual(rows['rental']['npv'],'18429831.59')
        fin=defaults();fin['contingency']=20
        self.assertEqual(calculate(fin,groups,1000)[1]['capex'],'82320000.00')

    def test_critical_missing_and_incompatible_hide_economy(self):
        c=self.setup_config();snap={int(k):v for k,v in c.snapshot.items()}
        first=c.assignments[0]['revision'];snap[first]['data']['runtime_h']=None
        result=evaluate(c.version.requirements,c.version.finance,c.assignments,snap)
        self.assertEqual(result['status'],'blocked');self.assertFalse(result['scenarios'])
        snap[first]['data']['runtime_h']=6;snap[first]['data']['payload_kg']=1
        result=evaluate(c.version.requirements,c.version.finance,c.assignments,snap)
        self.assertTrue(result['errors']);self.assertFalse(result['scenarios'])

    def test_shared_pool_does_not_duplicate_capacity(self):
        snap=catalog_snapshot();ident=next(i for i,r in snap.items() if 'универсальный' in r['data']['model'])
        req=default_requirements();req['peak_hour']=50
        asgn=[dict(operation=o['id'],group='one',kind='robot',revision=ident,count=1) for o in req['operations']]
        r=evaluate(req,defaults(),asgn,snap,False)
        self.assertEqual(len(r['groups']),1);self.assertEqual(r['status'],'incompatible');self.assertFalse(r['scenarios'])

    def test_graph_cycles_and_invalid_values_rejected(self):
        req=default_requirements();req['operations'][0]['predecessors']=['load']
        with self.assertRaises(ValueError):requirements(req,defaults())
        req=default_requirements();req['active_area']=1e6
        with self.assertRaises(ValueError):requirements(req,defaults())
        fin=defaults();fin['discount']='NaN'
        with self.assertRaises(ValueError):requirements(default_requirements(),fin)

    def test_partial_import_and_duplicate_guard(self):
        supplier=Supplier.objects.first();data=deepcopy(EquipmentRevision.objects.first().data)
        data.update(model='Imported',operations=','.join(data['operations']))
        import json
        data['rates']=json.dumps(data['rates'])
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=TEMPLATE,delimiter=';',extrasaction='ignore');writer.writeheader()
        writer.writerow(data);bad=dict(data,model='',width_m=-3);writer.writerow(bad)
        content=stream.getvalue().encode()
        batch=import_csv(self.admin,supplier,content,'test.csv')
        self.assertEqual(batch.rows.filter(error='').count(),1);self.assertEqual(batch.rows.exclude(error='').count(),1)
        self.assertEqual(import_csv(self.admin,supplier,content,'test.csv').pk,batch.pk)
        self.assertFalse(Equipment.objects.get(identity__contains='imported').published)

    def test_old_published_revision_and_snapshot_preserved(self):
        c=self.setup_config();rev=EquipmentRevision.objects.get(pk=c.assignments[0]['revision']);old=deepcopy(c.result)
        data=deepcopy(rev.data);data['purchase']+=100000
        new=submit(self.admin,rev.equipment.supplier,data,confirm=True)
        rev.equipment.refresh_from_db();self.assertEqual(rev.equipment.published_id,rev.pk)
        publish(new,self.admin,'published','Checked')
        c.refresh_from_db();self.assertEqual(c.result,old)
        response=self.client.post(f'/configurations/{c.pk}/request/',{'mode':'purchase'})
        self.assertContains(response,'актуальную проверку')

    def test_pages_and_permissions(self):
        c=self.setup_config()
        for url in ['/', '/studies/','/studies/new/',f'/studies/{c.version.study_id}/edit/',f'/studies/{c.version.study_id}/',f'/configurations/{c.pk}/',f'/versions/{c.version_id}/configure/','/requests/','/account/']:
            response=self.client.get(url);self.assertEqual(response.status_code,200,url)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/configurations/{c.pk}/').status_code,404)
        self.assertEqual(self.client.get(f'/configurations/{c.pk}/export/').status_code,404)
        rev=EquipmentRevision.objects.first()
        self.assertEqual(self.client.post(f'/equipment/{rev.pk}/moderate/',{'decision':'published'}).status_code,403)

    def test_requests_all_suppliers_and_demo_stages(self):
        c=self.setup_config()
        self.client.post(f'/configurations/{c.pk}/request/',{'mode':'rental'})
        p=Procurement.objects.get();parts=list(p.parts.all())
        self.assertEqual(len(parts),len({g['supplier'] for g in c.result['groups']}))
        self.client.post(f'/requests/{p.pk}/order/',{'action':'create'})
        self.assertFalse(DemoOrder.objects.exists())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/parts/{parts[0].pk}/').status_code,403)
        self.assertEqual(self.client.post(f'/parts/{parts[0].pk}/answer/',{'decision':'confirmed','text':'ok'}).status_code,403)
        for part in parts:
            part.supplier.members.add(self.other)
            response=self.client.get(f'/parts/{part.pk}/');self.assertNotContains(response,'3000000')
            self.client.post(f'/parts/{part.pk}/answer/',{'decision':'confirmed','text':'Каталожные условия подтверждены'})
        self.client.force_login(self.customer)
        self.client.post(f'/requests/{p.pk}/order/',{'action':'create'})
        order=DemoOrder.objects.get()
        self.client.post(f'/requests/{p.pk}/order/',{'action':'pay'});order.refresh_from_db();self.assertEqual(order.stage,'contracts')
        for part in parts:self.client.post(f'/requests/{p.pk}/order/',{'action':'contract','part':part.pk})
        self.client.post(f'/requests/{p.pk}/order/',{'action':'pay'});order.refresh_from_db();self.assertEqual(order.stage,'delivery')
        for part in parts:self.client.post(f'/requests/{p.pk}/order/',{'action':'installed','part':part.pk})
        self.client.post(f'/requests/{p.pk}/order/',{'action':'accept'});order.refresh_from_db();self.assertEqual(order.stage,'complete')

    def test_deadline_and_csrf(self):
        c=self.setup_config();self.client.post(f'/configurations/{c.pk}/request/',{'mode':'purchase'})
        p=Procurement.objects.get();Procurement.objects.filter(pk=p.pk).update(created_at=timezone.now()-timedelta(days=8))
        self.assertContains(self.client.get(f'/requests/{p.pk}/'),'семь дней')
        client=Client(enforce_csrf_checks=True);client.force_login(self.customer)
        self.assertEqual(client.post(f'/configurations/{c.pk}/request/',{'mode':'purchase'}).status_code,403)

    def test_study_name_and_export_formats(self):
        import json
        self.client.force_login(self.customer)
        payload={k:v for k,v in defaults().items() if v is not None}
        payload.update(project_name='Проверка склада',name='Название операции',requirements=json.dumps(default_requirements()))
        response=self.client.post('/studies/new/',payload)
        self.assertEqual(response.status_code,302);self.assertEqual(Study.objects.get().name,'Проверка склада')
        c=self.setup_config()
        for format,signature in [('pdf',b'%PDF'),('xlsx',b'PK')]:
            response=self.client.get(f'/configurations/{c.pk}/export/?format={format}')
            self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(signature))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/configurations/{c.pk}/export/?format=pdf').status_code,404)

    def test_demo_answers_cannot_confirm_real_supplier(self):
        c=self.setup_config();self.client.post(f'/configurations/{c.pk}/request/',{'mode':'purchase'})
        p=Procurement.objects.get();part=p.parts.first();part.supplier.demo=False;part.supplier.save()
        self.assertEqual(self.client.post(f'/requests/{p.pk}/demo-answers/').status_code,403)
        self.assertFalse(p.parts.filter(state='confirmed').exists())
        part.supplier.demo=True;part.supplier.save()
        self.assertEqual(self.client.post(f'/requests/{p.pk}/demo-answers/').status_code,302)
        self.assertFalse(p.parts.exclude(state='confirmed').exists())

    def test_simulation_parallel_join_and_charging(self):
        from .simulation import simulate
        req=default_requirements();req['routes']=[];req['peak_hour']=30
        template=req['operations'][0]
        req['operations']=[dict(template,id=k,name=k,predecessors=pred,route='',distance_m=0,buffer=1,stations=1) for k,pred in [('a',[]),('b',[]),('c',['a','b'])]]
        groups=[dict(id=k,kind='human',count=1,rate=60) for k in ['a','b','c']]
        sim=simulate(req,groups,{k:k for k in ['a','b','c']})
        self.assertTrue(sim['feasible'])
        events={e['operation']:e for e in sim['events'] if e['job']==0}
        self.assertEqual(events['a']['start'],events['b']['start'])
        self.assertGreaterEqual(events['c']['start'],max(events['a']['end'],events['b']['end']))
        req['operations']=req['operations'][:1];req['peak_hour']=60
        data=dict(rates={template['code']:120},speed_m_s=1,runtime_h=.05,charge_h=.1,width_m=1)
        sim=simulate(req,[dict(id='g',kind='robot',count=1,data=data)],{'a':'g'})
        self.assertGreater(sim['charging_events'],0);self.assertFalse(sim['feasible'])

    def test_jsonl_zip_import_and_unsafe_paths(self):
        import zipfile,subprocess,sys,tempfile
        from pathlib import Path
        from django.conf import settings
        from .catalog import import_jsonl_zip
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run([sys.executable,str(settings.BASE_DIR/'vendor/robot_parser/parser.py'),'--output',folder],check=True,capture_output=True)
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
                for file in Path(folder).rglob('*'):
                    if file.is_file():archive.write(file,file.relative_to(folder))
            batch=import_jsonl_zip(self.admin,stream.getvalue())
            self.assertGreater(batch.rows.count(),5)
            self.assertEqual(import_jsonl_zip(self.admin,stream.getvalue()).pk,batch.pk)
            self.assertEqual(Equipment.objects.filter(published__isnull=False).count(),3)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:archive.writestr('../cards.jsonl','{}')
        with self.assertRaises(ValueError):import_jsonl_zip(self.admin,stream.getvalue())

    def test_project_import_copy_delete_isolation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.customer)
        template=self.client.get('/studies/template/').content
        response=self.client.post('/studies/upload/',{'file':SimpleUploadedFile('process.csv',template)})
        self.assertEqual(response.status_code,302);study=Study.objects.get()
        self.client.post(f'/studies/{study.pk}/copy/');self.assertEqual(Study.objects.count(),2)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(f'/studies/{study.pk}/delete/',{'confirm':'delete'}).status_code,404)
        self.client.force_login(self.customer)
        self.client.post(f'/studies/{study.pk}/delete/',{'confirm':'delete'})
        self.assertEqual(Study.objects.count(),1)

    def test_sensitivity_and_horizon_are_explicit(self):
        c=self.setup_config();result=c.result
        self.assertEqual(len(result['sensitivity']),6)
        self.assertEqual(len({r['parameter'] for r in result['sensitivity']}),3)
        self.assertTrue(result['load_limit'])
        s=result['scenarios'][1]
        self.assertAlmostEqual(s['roi']-s['net_roi'],100)
        self.assertEqual(sum(float(v) for v in s['capex_items'].values()),float(s['capex']))
        fin=defaults();fin['horizon']=10
        self.assertEqual(len(calculate(fin,result['groups'],10000)[1]['flows']),10)

    def test_alternative_rechecks_complete_chain(self):
        c=self.setup_config();self.client.post(f'/configurations/{c.pk}/request/',{'mode':'purchase'})
        part=SupplierRequest.objects.filter(items__isnull=False).first()
        self.client.force_login(self.admin)
        revision=Equipment.objects.filter(supplier=part.supplier,published__isnull=False).first().published
        data=deepcopy(revision.data);data['payload_kg']=1
        revision=submit(self.admin,part.supplier,data,confirm=True);publish(revision,self.admin,'published','test')
        self.client.post(f'/parts/{part.pk}/answer/',{'decision':'alternative','alternative':revision.pk,'text':'Another model'})
        self.client.force_login(self.customer)
        response=self.client.post(f'/parts/{part.pk}/alternative/')
        self.assertEqual(response.status_code,302)
        new=Configuration.objects.latest('id');self.assertFalse(new.result['scenarios']);self.assertTrue(new.result['errors'])
        c.refresh_from_db();self.assertTrue(c.result['scenarios'])
