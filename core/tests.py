from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse


class CoreDashboardTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='doctor_test', password='password123')

    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_authenticated_dashboard(self):
        self.client.login(username='doctor_test', password='password123')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'dashboard.html')
