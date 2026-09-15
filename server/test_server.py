import unittest
import json
import os
import shutil
import tempfile
import server

class TestServer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_workspace = server.WORKSPACE_DIR
        server.WORKSPACE_DIR = self.test_dir
        server.OUTPUT_FILE = os.path.join(self.test_dir, 'workouts.json')
        server.LOG_FILE = os.path.join(self.test_dir, 'server_log.txt')
        
        import etl_parser
        self.old_etl_workspace = etl_parser.WORKSPACE_DIR
        etl_parser.WORKSPACE_DIR = self.test_dir
        etl_parser.INPUT_FILE = os.path.join(self.test_dir, 'workouts.json')
        etl_parser.DB_FILE = os.path.join(self.test_dir, 'baza_kalistenika.db')
        
        self.app = server.app.test_client()
        self.app.testing = True

    def tearDown(self):
        server.WORKSPACE_DIR = self.old_workspace
        server.OUTPUT_FILE = os.path.join(self.old_workspace, 'workouts.json')
        server.LOG_FILE = os.path.join(self.old_workspace, 'server_log.txt')
        
        import etl_parser
        etl_parser.WORKSPACE_DIR = self.old_etl_workspace
        etl_parser.INPUT_FILE = os.path.join(self.old_etl_workspace, 'workouts.json')
        etl_parser.DB_FILE = os.path.join(self.old_etl_workspace, 'baza_kalistenika.db')
        
        shutil.rmtree(self.test_dir)

    def test_voice_endpoint_success(self):
        test_text = "Testowa notatka"
        response = self.app.post('/voice', json={"text": test_text})
        self.assertEqual(response.status_code, 200)
        
        inbox_path = os.path.join(self.test_dir, 'voice_inbox.md')
        with open(inbox_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn(test_text, content)

    def test_etl_endpoint(self):
        payload = {
            "steps": [{"start_time": "2026-09-15T10:00:00Z", "count": 1000}],
            "exercise": [{"start_time": "2026-09-15T12:00:00Z", "end_time": "2026-09-15T13:00:00Z", "type": "running", "duration_seconds": 3600}]
        }
        response = self.app.post('/', json=payload)
        self.assertEqual(response.status_code, 200)
        
        with open(server.OUTPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data['workouts']), 1)
            self.assertEqual(data['workouts'][0]['steps'][0]['count'], 1000)
            
        import sqlite3
        import etl_parser
        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            c.execute("SELECT kroki FROM metryki_dzienne WHERE data='2026-09-15'")
            row = c.fetchone()
            self.assertIsNotNone(row, "Dane nie zostały zapisane do bazy - sprawdź server_log.txt")
            self.assertEqual(row[0], 1000)
        finally:
            conn.close()

    def test_telegram_format_strips_file_links(self):
        raw = "Dziś masz REST DAY (patrz: [PROJECT_STATE.md](file:///c:/Users/TESTUSER/PROJECT_STATE.md)), a bilans..."
        formatted = server.format_telegram_message(raw)
        self.assertNotIn("file:///", formatted)
        self.assertNotIn("PROJECT_STATE.md", formatted)
        self.assertIn("Dziś masz REST DAY, a bilans...", formatted)

    def test_telegram_format_converts_table(self):
        raw = """| Składnik | Wariant A | Wariant B |
| :--- | :--- | :--- |
| Kcal | 500 kcal | 450 kcal |"""
        formatted = server.format_telegram_message(raw)
        self.assertNotIn("| :--- |", formatted)
        self.assertIn("<b>Wariant A</b>", formatted)
        self.assertIn("• Kcal: 500 kcal", formatted)
        self.assertIn("<b>Wariant B</b>", formatted)
        self.assertIn("• Kcal: 450 kcal", formatted)

    def test_telegram_format_escapes_html(self):
        raw = "Węgle < 50g & tłuszcze > 70g"
        formatted = server.format_telegram_message(raw)
        self.assertIn("&lt;", formatted)
        self.assertIn("&gt;", formatted)
        self.assertIn("&amp;", formatted)

if __name__ == '__main__':
    unittest.main()
