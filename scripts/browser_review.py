"""Local browser QA, including staff-only views; no reusable password is created."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.conf import settings
if settings.PASSWORDLESS_DEMO:
    import runpy
    runpy.run_path(str(ROOT/'scripts/check_roles_template_browser.py'),run_name='__main__')
    raise SystemExit(0)
from django.contrib.auth import get_user_model
from django.test import Client
from django.core.management import call_command
from django.contrib.sessions.models import Session
from workflow.models import Robot
from playwright.sync_api import sync_playwright

user, created = get_user_model().objects.get_or_create(username='local-review', defaults={'is_staff': True})
if created:
    user.set_unusable_password(); user.save()
assert user.is_staff
assert not user.has_usable_password(), 'Use a dedicated account with an unusable password'
for previous in Session.objects.all():
    if previous.get_decoded().get('_auth_user_id') == str(user.pk):
        previous.delete()
call_command('initialize_workflow')
client = Client(); client.force_login(user)
import atexit
atexit.register(client.logout)
session = client.cookies['sessionid'].value
robot = Robot.objects.filter(field_observations__isnull=False).first()
out = ROOT / 'test-results' / 'ui'; out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    for width, height, name in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
        context = browser.new_context(viewport={'width': width, 'height': height})
        page = context.new_page()
        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
        for url, label in [('/', 'home'), ('/account/?role=admin', 'login'), ('/legacy/', 'guest')]:
            page.goto('http://127.0.0.1:8765' + url)
            page.screenshot(path=str(out / f'{name}-{label}.png'), full_page=True)
            page.screenshot(path=str(out / f'{name}-{label}-viewport.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), label
        context.add_cookies([{'name': 'sessionid', 'value': session, 'domain': '127.0.0.1', 'path': '/'}])
        for url, label in [('/workspace/robots/', 'catalog'), ('/workspace/sources/', 'sources'), ('/studies/new/', 'project'), (f'/workspace/robots/{robot.pk}/', 'review')]:
            response = page.goto('http://127.0.0.1:8765' + url)
            assert response.status == 200, (url, response.status)
            page.screenshot(path=str(out / f'{name}-{label}.png'), full_page=True)
            page.screenshot(path=str(out / f'{name}-{label}-viewport.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), label
        assert not errors, errors
        print(name, '7 pages: OK, no overflow or JS errors')
        context.close()
    browser.close()
# Invalidate the one-off review session after screenshots.
client.logout()
