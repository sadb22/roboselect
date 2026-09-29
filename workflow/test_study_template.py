import csv
import io
import json
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from .domain import default_requirements
from .finance import defaults
from .models import Study, StudyVersion


@override_settings(PASSWORDLESS_DEMO=True)
class StudyTemplateTests(TestCase):
    def setUp(self):
        self.client.post('/enter/user/')

    def form_data(self):
        return dict({k: '' if v is None else v for k,v in defaults().items()}, project_name='Мой склад', requirements=json.dumps(default_requirements()))

    def file(self, area=22000):
        content=self.client.get('/studies/template/').content.decode('utf-8-sig')
        rows=list(csv.DictReader(io.StringIO(content), delimiter=';'))
        for row in rows:
            if row['key']=='area':row['value']=str(area)
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['section','key','value'],delimiter=';')
        writer.writeheader();writer.writerows(rows)
        return SimpleUploadedFile('warehouse.csv',stream.getvalue().encode('utf-8'))

    def test_load_preview_then_save(self):
        self.assertContains(self.client.get('/studies/new/'),'Скачать шаблон склада')
        response=self.client.post('/studies/new/',dict(self.form_data(),action='load_template',file=self.file()))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['requirements']['area'],22000)
        self.assertEqual(response.context['name'],'Мой склад')
        self.assertFalse(Study.objects.exists())
        req=response.context['requirements'];fin={k:'' if v is None else v for k,v in response.context['finance_form'].initial.items()}
        response=self.client.post('/studies/new/',dict(fin,project_name='Мой склад',requirements=json.dumps(req)))
        self.assertEqual(response.status_code,302)
        self.assertEqual(StudyVersion.objects.get().requirements['area'],22000)

    def test_bad_upload_preserves_unsaved_form(self):
        data=self.form_data();req=default_requirements();req['area']=33000
        data['requirements']=json.dumps(req);data['staff']=42
        response=self.client.post('/studies/new/',dict(data,action='load_template',file=SimpleUploadedFile('bad.csv',b'wrong;headers\n1;2')))
        self.assertContains(response,'Нужен CSV-шаблон склада')
        self.assertEqual(response.context['requirements']['area'],33000)
        self.assertEqual(response.context['finance_form']['staff'].value(),'42')
        self.assertFalse(Study.objects.exists())

    def test_edit_import_does_not_change_saved_version(self):
        response=self.client.post('/studies/new/',self.form_data())
        study=Study.objects.get();original=study.versions.get().requirements
        url=f'/studies/{study.pk}/edit/'
        response=self.client.post(url,dict(self.form_data(),action='load_template',file=self.file()))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['requirements']['area'],22000)
        self.assertEqual(study.versions.count(),1)
        self.assertEqual(study.versions.get().requirements,original)

    def test_invalid_ranges_do_not_create_project(self):
        response=self.client.post('/studies/new/',dict(self.form_data(),action='load_template',file=self.file(area=-1)))
        self.assertContains(response,'допустимо')
        self.assertFalse(Study.objects.exists())
