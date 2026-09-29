from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from workflow.models import Study


@override_settings(PASSWORDLESS_DEMO=True)
class PasswordlessDemoTests(TestCase):
    def test_all_workspaces_open_without_login(self):
        for url in ('/', '/user/', '/studies/', '/studies/new/', '/requests/', '/legacy/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.get('/')
        self.assertNotContains(response, 'Войти')
        self.assertNotContains(response, 'Регистрация')
        self.assertContains(response, 'Вход как администратор')
        self.assertContains(response, 'Вход как пользователь')
        self.assertNotIn('_auth_user_id', self.client.session)
        user = get_user_model().objects.get(pk=self.client.session['demo_visitor_id'])
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_superuser)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_old_login_links_and_auth_api(self):
        self.assertRedirects(self.client.get('/account/?role=admin'), '/')
        self.assertRedirects(self.client.get('/account/'), '/')
        self.assertRedirects(self.client.get('/admin/login/'), '/')
        for action in ('login', 'logout', 'register'):
            self.assertEqual(self.client.post(f'/api/auth/{action}/', {}).status_code, 404)

    def test_save_reopen_and_isolate_browser_projects(self):
        template = self.client.get('/studies/template/').content
        response = self.client.post('/studies/upload/', {'file': SimpleUploadedFile('project.csv', template)})
        self.assertEqual(response.status_code, 302)
        study = Study.objects.get()
        self.assertEqual(self.client.get(response.url).status_code, 200)
        self.assertEqual(study.owner_id, self.client.session['demo_visitor_id'])
        other = Client()
        self.assertEqual(other.get(response.url).status_code, 404)
        self.assertNotContains(other.get('/studies/'), study.name)
        self.assertEqual(other.post(f'/studies/{study.pk}/delete/', {'confirm':'delete'}).status_code, 404)
        self.assertTrue(Study.objects.filter(pk=study.pk).exists())

    def test_demo_does_not_reuse_existing_authenticated_owner(self):
        owner = get_user_model().objects.create_user(username='existing', password='previous-password')
        study = Study.objects.create(owner=owner, name='Private project')
        self.client.force_login(owner)
        self.assertEqual(self.client.get(f'/studies/{study.pk}/').status_code, 404)
        self.assertNotEqual(self.client.session['demo_visitor_id'], owner.pk)

    def test_disabling_mode_does_not_leave_an_admin_login(self):
        self.client.post('/enter/admin/')
        self.client.get('/workspace/robots/')
        with override_settings(PASSWORDLESS_DEMO=False):
            self.assertEqual(self.client.get('/workspace/robots/').status_code, 302)

    def test_csrf_still_required(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/workspace/sources/')
        self.assertEqual(client.post('/workspace/sources/', {'url':'https://example.org'}).status_code, 403)

    def test_catalogue_requires_selected_admin_role(self):
        self.client.post('/enter/user/')
        urls = ['/workspace/', '/workspace/robots/', '/workspace/sources/', '/workspace/template/',
                '/equipment/new/', '/equipment/123/edit/', '/equipment/123/', '/batches/123/']
        for url in urls:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code, 403)
        for url in ['/workspace/upload/', '/workspace/parser/', '/workspace/sources/',
                    '/equipment/123/moderate/', '/api/catalog/import/']:
            with self.subTest(url=url):self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.assertNotContains(self.client.get('/user/'), 'Ассортимент')
        self.assertNotContains(self.client.get('/user/'), 'База роботов')
        self.assertRedirects(self.client.post('/enter/admin/'), '/workspace/robots/')
        for url in ['/workspace/', '/workspace/robots/', '/workspace/sources/', '/equipment/new/']:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post('/enter/user/')
        self.assertEqual(self.client.get('/workspace/robots/').status_code, 403)
        visitor=get_user_model().objects.get(pk=self.client.session['demo_visitor_id'])
        self.assertFalse(visitor.is_staff)

    def test_role_change_is_post_only_and_csrf_protected(self):
        self.assertEqual(self.client.get('/enter/admin/').status_code, 405)
        client=Client(enforce_csrf_checks=True)
        client.get('/')
        self.assertEqual(client.post('/enter/admin/').status_code, 403)
