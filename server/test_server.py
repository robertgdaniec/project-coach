import unittest
import json
import os
import sys
import shutil
import tempfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

try:
    import server
    if not hasattr(server, 'WORKSPACE_DIR'):
        import server.server as server
except ImportError:
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

    def test_etl_defensive_calories_mapping(self):
        import sqlite3
        import etl_parser

        # Scenariusz A: Tylko active_calories
        payload_a = {
            "active_calories": [{"start_time": "2026-09-16T08:00:00Z", "calories": 420.0}]
        }
        res_a = self.app.post('/', json=payload_a)
        self.assertEqual(res_a.status_code, 200)

        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-16'")
            row = c.fetchone()
            self.assertIsNotNone(row)
            self.assertAlmostEqual(row[0], 420.0, places=1)
        finally:
            conn.close()

        # Scenariusz B: Tylko total_calories (obecny fallback Samsung Health)
        payload_b = {
            "total_calories": [{"start_time": "2026-09-17T08:00:00Z", "calories": 180.5}]
        }
        res_b = self.app.post('/', json=payload_b)
        self.assertEqual(res_b.status_code, 200)

        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-17'")
            row = c.fetchone()
            self.assertIsNotNone(row)
            self.assertAlmostEqual(row[0], 180.5, places=1)
        finally:
            conn.close()

        # Scenariusz C: Obie wartości dla tej samej daty (active_calories ma pierwszeństwo)
        payload_c = {
            "active_calories": [{"start_time": "2026-09-18T12:00:00Z", "calories": 350.0}],
            "total_calories": [{"start_time": "2026-09-18T12:00:00Z", "calories": 180.5}]
        }
        res_c = self.app.post('/', json=payload_c)
        self.assertEqual(res_c.status_code, 200)

        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-18'")
            row = c.fetchone()
            self.assertIsNotNone(row)
            self.assertAlmostEqual(row[0], 350.0, places=1)
        finally:
            conn.close()

        # Scenariusz D: Multi-day sliding window (D-1 ma active_calories, D ma wyłącznie total_calories)
        payload_d = {
            "active_calories": [
                {"start_time": "2026-09-19T10:00:00Z", "calories": 33.5}
            ],
            "total_calories": [
                {"start_time": "2026-09-19T10:00:00Z", "calories": 33.5},
                {"start_time": "2026-09-20T08:00:00Z", "calories": 237.0}
            ]
        }
        res_d = self.app.post('/', json=payload_d)
        self.assertEqual(res_d.status_code, 200)

        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            # Weryfikacja D-1 (2026-09-19) -> active_calories
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-19'")
            row_prev = c.fetchone()
            self.assertIsNotNone(row_prev)
            self.assertAlmostEqual(row_prev[0], 33.5, places=1)

            # Weryfikacja D (2026-09-20) -> total_calories (brak active_calories dla tej daty)
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-20'")
            row_curr = c.fetchone()
            self.assertIsNotNone(row_curr, "Dzień D nie został zapisany w metrykach dziennych!")
            self.assertIsNotNone(row_curr[0], "Dzień D nie otrzymał kalorii z total_calories (pole pozostało puste/None)!")
            self.assertAlmostEqual(row_curr[0], 237.0, places=1)
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

    def test_telegram_format_strips_policy_denial(self):
        raw = 'Denied by policy "confirm_run_command". ("denied by pre-tool hook: Denied by policy \\"confirm_run_command\\".")Zaktualizowano dzisiejsze śniadanie w dzienniku'
        formatted = server.format_telegram_message(raw)
        self.assertNotIn("Denied by policy", formatted)
        self.assertNotIn("confirm_run_command", formatted)
        self.assertNotIn("denied by pre-tool hook", formatted)
        self.assertIn("Zaktualizowano dzisiejsze śniadanie w dzienniku", formatted)

    def test_telegram_format_handles_github_alerts(self):
        raw = """> [!NOTE]
> ### 🎯 Odprawa D24 | TRAINING DAY
> **Waga:** 82.5 kg"""
        formatted = server.format_telegram_message(raw)
        self.assertNotIn("[!NOTE]", formatted)
        self.assertNotIn("&gt;", formatted)
        self.assertIn("💡", formatted)
        self.assertIn("<b>🎯 Odprawa D24 | TRAINING DAY</b>", formatted)
        self.assertIn("<b>Waga:</b> 82.5 kg", formatted)

    def test_key_pool_default_model_initialization(self):
        pool = server.GeminiKeyPool(keys=["key_test"])
        self.assertEqual(pool.model_name, "gemini-3.6-flash")

if __name__ == '__main__':
    unittest.main()
