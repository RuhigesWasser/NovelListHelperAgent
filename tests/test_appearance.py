import json
import unittest
import test_app


class AppearanceTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    post=test_app.AppTests.post

    def test_theme_is_persistent_and_rendered_before_styles_load(self):
        self.assertEqual(self.client.get('/api/appearance',headers=self.headers).json(),{'theme':'system'})
        for theme in ('dark','light','system'):
            response=self.post('/api/appearance',{'theme':theme})
            self.assertEqual(response.status_code,200)
            self.assertEqual(json.loads((self.local/'ui-settings.json').read_text())['theme'],theme)
            self.assertIn(f'data-theme="{theme}"',self.client.get('/').text)

    def test_theme_rejects_unknown_values_and_unauthenticated_writes(self):
        self.assertEqual(self.post('/api/appearance',{'theme':'invalid'}).status_code,422)
        self.assertEqual(self.client.post('/api/appearance',json={'theme':'dark'}).status_code,403)
