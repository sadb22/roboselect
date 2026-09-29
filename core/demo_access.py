"""Passwordless demo workspaces without exposing existing account-owned projects."""
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import redirect


class PasswordlessDemoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.passwordless_demo = settings.PASSWORDLESS_DEMO
        if not settings.PASSWORDLESS_DEMO:
            return self.get_response(request)
        if request.path.startswith('/api/auth/'):
            return JsonResponse({'error': 'В демонстрационном режиме вход не требуется'}, status=404)
        if request.path.startswith('/admin/'):
            return redirect('/workspace/robots/' if request.session.get('demo_role') == 'admin' else '/')
        if request.path == '/account/':
            return redirect('/')
        if request.path.startswith('/static/') or request.path in ('/health/', '/api/worker-health/'):
            return self.get_response(request)
        User = get_user_model()
        visitor = User.objects.filter(pk=request.session.get('demo_visitor_id'),
            username__startswith='demo-visitor-', is_active=True, is_superuser=False).first()
        if visitor is None or visitor.has_usable_password():
            visitor = User.objects.create_user(username='demo-visitor-' + uuid.uuid4().hex,
                password=None, is_staff=False, is_superuser=False)
            request.session['demo_visitor_id'] = visitor.pk
        if visitor.is_staff:
            visitor.is_staff = False
            visitor.save(update_fields=['is_staff'])
        # Demo role is session-scoped; direct catalogue URLs never grant it.
        request.demo_role = request.session.get('demo_role', 'user')
        visitor.is_staff = request.demo_role == 'admin'
        # A technical owner retains existing FKs and audit history. No login or password.
        # No Django-auth session is created, so disabling this mode never grants staff access.
        request.user = visitor
        return self.get_response(request)
