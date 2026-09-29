from django.test import override_settings
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from .catalog import import_parser, publish
from .provenance import ingest, select_value
from .provenance_models import *


@override_settings(PASSWORDLESS_DEMO=False)
class ProvenanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user('reviewer', password='test-password', is_staff=True)
        cls.client_user = get_user_model().objects.create_user('customer', password='test-password')

    def export(self, folder):
        subprocess.run([sys.executable, '-X', 'utf8', str(settings.BASE_DIR / 'vendor/robot_parser/parser.py'), '--output', folder], check=True, capture_output=True)

    def test_import_repeat_review_and_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            self.export(folder)
            batch = import_parser(self.admin, folder)
            first_count = FieldObservation.objects.count()
            self.export(folder)
            self.assertEqual(import_parser(self.admin, folder).pk, batch.pk)
            self.assertEqual(FieldObservation.objects.count(), first_count)
            self.assertEqual(Robot.objects.count(), 5)
            self.assertGreater(RobotOffer.objects.count(), 0)
            self.assertEqual(FieldSelection.objects.count(), 0)
            observation = FieldObservation.objects.filter(field='payload', extraction_state='parsed').first()
            select_value(self.admin, observation.pk, 'accepted')
            ingest(folder)
            observation.refresh_from_db()
            self.assertEqual(observation.review_state, 'accepted')
            self.assertEqual(FieldSelection.objects.filter(current=True).count(), 1)
            self.assertTrue(WarehouseSpec.objects.filter(robot=observation.robot).exists())
            revision = observation.robot.equipment.revisions.latest('id')
            # Parse candidates do not become verified merely by publishing a draft.
            publish(revision, self.admin, 'published', '')
            revision.refresh_from_db()
            self.assertIsNone(revision.data['width_m'])

    def test_tampered_snapshot_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            self.export(folder)
            s = json.loads((Path(folder) / 'snapshots.jsonl').read_text(encoding='utf-8').splitlines()[0])
            (Path(folder) / s['stored_path']).write_bytes(b'tampered')
            with self.assertRaisesMessage(ValueError, 'Контрольная сумма'):
                import_parser(self.admin, folder)
            self.assertFalse(Robot.objects.exists())

    def test_new_conflict_preserves_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            self.export(folder); ingest(folder)
            chosen = FieldObservation.objects.filter(field='payload', extraction_state='parsed').first()
            select_value(self.admin, chosen.pk, 'accepted')
            path = Path(folder) / 'observations.jsonl'
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            candidate = next(r for r in rows if r['observation_id'] == chosen.key)
            candidate['observation_id'] = 'new-parser-candidate'
            candidate['normalized'] = {'value': 999, 'unit': 'кг'}
            path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            ingest(folder)
            self.assertEqual(FieldSelection.objects.get(current=True).observation_id, chosen.pk)
            self.assertTrue(ReviewIssue.objects.filter(key='conflict-new-parser-candidate', status='open').exists())

    def test_issue_resolution_requires_staff_and_reason(self):
        observation = self.fixture()
        issue = ReviewIssue.objects.create(key='issue', robot=observation.robot, reason='Conflict')
        url = f'/workspace/issues/{issue.pk}/resolve/'
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.post(url, {'reason': 'checked'}).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(url, {'reason': ''})
        issue.refresh_from_db(); self.assertEqual(issue.status, 'open')
        self.client.post(url, {'reason': 'Выбрана актуальная спецификация'})
        issue.refresh_from_db(); self.assertEqual(issue.status, 'resolved')
        self.assertEqual(issue.reviewer_id, self.admin.pk)

    def fixture(self):
        r = Robot.objects.create(key='test', name='Test')
        s = Source.objects.create(key='test', location='file.txt', kind='txt')
        snapshot = SourceSnapshot.objects.create(key='test', source=s, sha256=hashlib.sha256(b'test').hexdigest(), stored_path='file.txt', content=b'test', parser_version='test')
        return FieldObservation.objects.create(key='first', robot=r, snapshot=snapshot, field='payload', raw_text='Грузоподъемность 100 кг', normalized={'value': 100, 'unit': 'кг', 'qualifier': None}, extraction_state='parsed')

    def test_decision_history_and_access(self):
        first = self.fixture()
        second = FieldObservation.objects.create(key='second', robot=first.robot, snapshot=first.snapshot, field='payload', raw_text='200 кг', normalized={'value': 200, 'unit': 'кг'}, extraction_state='parsed')
        with self.assertRaises(PermissionError):
            select_value(self.client_user, first.pk, 'accepted')
        select_value(self.admin, first.pk, 'accepted')
        select_value(self.admin, second.pk, 'accepted')
        self.assertEqual(FieldSelection.objects.count(), 2)
        self.assertEqual(FieldSelection.objects.get(current=True).observation, second)
        self.assertEqual(WarehouseSpec.objects.get(robot=first.robot).values['payload']['value'], 200)

    def test_invalid_observation_not_accepted(self):
        observation = self.fixture()
        observation.extraction_state = 'unrecognized'; observation.save()
        with self.assertRaises(ValueError):
            select_value(self.admin, observation.pk, 'accepted')
        self.assertFalse(FieldSelection.objects.exists())

    def test_complete_unknown_source_without_duplicate_robot(self):
        from .models import Supplier
        observation = self.fixture()
        supplier = Supplier.objects.create(name='Explicit supplier')
        self.client.force_login(self.admin)
        url = f'/workspace/robots/{observation.robot_id}/card/'
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'supplier': supplier.pk, 'manufacturer': 'Confirmed maker',
            'model': 'Test R100', 'source': 'file.txt', 'configuration': 'Base',
            'operations': ['warehouse_pallet_transport']})
        self.assertEqual(response.status_code, 302)
        observation.robot.refresh_from_db()
        self.assertIsNotNone(observation.robot.equipment_id)
        self.assertEqual(Robot.objects.count(), 1)
        self.assertIsNone(observation.robot.equipment.published_id)

    def test_pages_and_snapshot_staff_only(self):
        observation = self.fixture()
        urls = ['/workspace/robots/', f'/workspace/robots/{observation.robot_id}/', '/workspace/sources/', f'/workspace/snapshots/{observation.snapshot_id}/']
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.client_user)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_role_selection_does_not_grant_rights(self):
        self.assertEqual(self.client.post('/api/auth/login/', json.dumps({'username': 'customer', 'password': 'test-password', 'role': 'admin'}), content_type='application/json').status_code, 403)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.post('/api/auth/register/', {}).status_code, 404)
        response = self.client.get('/user/')
        self.assertContains(response, 'Войти как администратор')
        self.assertContains(response, 'Регистрация временно недоступна.')

    def test_private_network_url_rejected_and_status_saved(self):
        from .web_import import add_web_source
        with patch('workflow.web_import.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaisesMessage(ValueError, 'Локальные'):
                add_web_source(self.admin, 'https://example.test/robot')
        self.assertEqual(Source.objects.get().status, 'error')

    def test_fixture_html_import(self):
        from .web_import import add_web_source
        raw = b'<html><main><h1>Acme R100</h1><table><tr><td>Payload, kg</td><td>100</td></tr></table></main></html>'
        with patch('workflow.web_import.fetch', return_value=raw):
            add_web_source(self.admin, 'https://example.test/robot')
        self.assertTrue(FieldObservation.objects.exists())
        self.assertFalse(FieldSelection.objects.exists())

    def test_unsupported_html_is_error(self):
        from .web_import import add_web_source
        with patch('workflow.web_import.fetch', return_value=b'<h1>R100</h1><p>No specs</p>'):
            with self.assertRaises(ValueError):
                add_web_source(self.admin, 'https://example.test/robot')
        self.assertEqual(Source.objects.get().status, 'error')
        self.assertFalse(Robot.objects.exists())
