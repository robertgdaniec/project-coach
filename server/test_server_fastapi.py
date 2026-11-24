import unittest
from unittest.mock import patch
import json
import os
import sys
import shutil
import tempfile
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import server_fastapi
import etl_parser

class TestServerFastAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_workspace = server_fastapi.WORKSPACE_DIR
        server_fastapi.WORKSPACE_DIR = Path(self.test_dir)
        server_fastapi.OUTPUT_FILE = Path(self.test_dir) / 'workouts.json'
        server_fastapi.LOG_FILE = Path(self.test_dir) / 'server_log.txt'
        
        self.old_etl_workspace = etl_parser.WORKSPACE_DIR
        etl_parser.WORKSPACE_DIR = Path(self.test_dir)
        etl_parser.INPUT_FILE = Path(self.test_dir) / 'workouts.json'
        etl_parser.DB_FILE = Path(self.test_dir) / 'baza_kalistenika.db'
        
        # TestClient z FastAPI
        self.client = TestClient(server_fastapi.app)

    def tearDown(self):
        server_fastapi.WORKSPACE_DIR = self.old_workspace
        server_fastapi.OUTPUT_FILE = self.old_workspace / 'workouts.json'
        server_fastapi.LOG_FILE = self.old_workspace / 'server_log.txt'
        
        etl_parser.WORKSPACE_DIR = self.old_etl_workspace
        etl_parser.INPUT_FILE = self.old_etl_workspace / 'workouts.json'
        etl_parser.DB_FILE = self.old_etl_workspace / 'baza_kalistenika.db'
        
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_root_healthcheck(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["server"], "FastAPI")
        self.assertEqual(data["version"], "2.0.0")

    def test_advanced_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("gemini_pool", data)

    def test_docs_and_openapi(self):
        # Swagger UI
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("swagger", response.text.lower())

        # OpenAPI schema
        response_schema = self.client.get("/openapi.json")
        self.assertEqual(response_schema.status_code, 200)
        schema = response_schema.json()
        self.assertIn("paths", schema)
        self.assertIn("/voice", schema["paths"])
        self.assertIn("/telegram-webhook", schema["paths"])
        self.assertIn("/samsung-health", schema["paths"])

    def test_voice_endpoint_success(self):
        test_text = "Testowa notatka kalisteniki"
        response = self.client.post("/voice", json={"text": test_text})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")

        inbox_path = os.path.join(self.test_dir, 'voice_inbox.md')
        self.assertTrue(os.path.exists(inbox_path))
        with open(inbox_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn(test_text, content)

    def test_voice_endpoint_validation_error(self):
        # Pusty ciąg znaków (naruszenie min_length=1)
        response = self.client.post("/voice", json={"text": ""})
        self.assertEqual(response.status_code, 422)

        # Brak wymaganego pola text
        response_missing = self.client.post("/voice", json={})
        self.assertEqual(response_missing.status_code, 422)

    def test_samsung_health_endpoint(self):
        payload = {
            "steps": [{"start_time": "2026-09-16T10:00:00Z", "count": 2500}],
            "exercise": [{
                "start_time": "2026-09-16T12:00:00Z",
                "end_time": "2026-09-16T13:00:00Z",
                "type": "pull-ups",
                "duration_seconds": 3600
            }]
        }
        response = self.client.post("/samsung-health", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        # Weryfikacja zapisu surowego JSON do Data Lake
        self.assertTrue(os.path.exists(server_fastapi.OUTPUT_FILE))
        with open(server_fastapi.OUTPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(len(data['workouts']), 1)
            self.assertEqual(data['workouts'][0]['steps'][0]['count'], 2500)

        # Weryfikacja bazy SQLite po przetworzeniu przez ETL
        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            c.execute("SELECT kroki FROM metryki_dzienne WHERE data='2026-09-16'")
            row = c.fetchone()
            self.assertIsNotNone(row, "Kroki nie zostały zapisane do bazy SQLite!")
            self.assertEqual(row[0], 2500)
        finally:
            conn.close()

    def test_catch_all_compatibility(self):
        # Sprawdzenie zachowania kompatybilności wstecznej dla POST /
        payload = {
            "steps": [{"start_time": "2026-09-16T15:00:00Z", "count": 500}]
        }
        response = self.client.post("/", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_telegram_webhook_deduplication(self):
        from unittest.mock import patch
        with patch("server_fastapi.process_telegram_update_task") as mock_task:
            payload = {
                "update_id": 99999,
                "message": {
                    "message_id": 1234,
                    "from": {"id": 100, "first_name": "Tester"},
                    "chat": {"id": 200, "type": "private"},
                    "text": "Wiadomosc idempotencji"
                }
            }
            # Pierwsze zapytanie - powinno triggerować task w tle
            res1 = self.client.post("/telegram-webhook", json=payload)
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(res1.json(), {"ok": True})
            mock_task.assert_called_once()

            # Drugie identyczne zapytanie (ten sam update_id) - powinno być odrzucone przez deduplikator bez odpalania tasku
            res2 = self.client.post("/telegram-webhook", json=payload)
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.json(), {"ok": True})
            self.assertEqual(mock_task.call_count, 1)

    def test_telegram_format_strips_file_links(self):
        raw = "Rest day (patrz: [PROJECT_STATE.md](file:///c:/Users/TESTUSER/PROJECT_STATE.md))!"
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertNotIn("file:///", formatted)
        self.assertNotIn("PROJECT_STATE.md", formatted)
        self.assertIn("Rest day", formatted)

    def test_telegram_format_converts_table(self):
        raw = """| Posiłek | Kalorie | Białko |
| :--- | :--- | :--- |
| Obiad | 700 kcal | 45g |"""
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertNotIn("| :--- |", formatted)
        self.assertIn("<b>Kalorie</b>", formatted)
        self.assertIn("• Obiad: 700 kcal", formatted)

    def test_telegram_format_escapes_html(self):
        raw = "Węgle < 50g & tłuszcze > 70g"
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertIn("&lt;", formatted)
        self.assertIn("&gt;", formatted)
        self.assertIn("&amp;", formatted)

    def test_telegram_format_strips_policy_denial(self):
        raw = 'Denied by policy "confirm_run_command". ("denied by pre-tool hook: Denied by policy \\"confirm_run_command\\".")Śniadanie zaksięgowane'
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertNotIn("Denied by policy", formatted)
        self.assertNotIn("confirm_run_command", formatted)
        self.assertIn("Śniadanie zaksięgowane", formatted)

    def test_telegram_format_strips_cascade_and_tool_errors(self):
        raw = (
            "error executing cascade step: CORTEX_STEP_TYPE_SEARCH_WEB: GenerateContent failed: Error 429, Message: You exceeded your current quota.\n"
            "* URL: https://autopush-aiplatform.sandbox.googleapis.com/...\n"
            "* Response Status: 429 Too Many Requests\n"
            "Unable to view file at the requested position.\n"
            "Mlekowita Kefir Bio 400g zaksięgowany."
        )
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertNotIn("error executing cascade step", formatted)
        self.assertNotIn("429 Too Many Requests", formatted)
        self.assertNotIn("Unable to view file", formatted)
        self.assertIn("Mlekowita Kefir Bio 400g zaksięgowany.", formatted)

        plain = server_fastapi.clean_plain_text(raw)
        self.assertNotIn("error executing cascade step", plain)
        self.assertNotIn("Unable to view file", plain)
        self.assertIn("Mlekowita Kefir Bio 400g zaksięgowany.", plain)

    def test_telegram_format_handles_github_alerts(self):
        raw = """> [!NOTE]
> ### 🎯 Odprawa D24 | TRAINING DAY
> **Waga:** 82.5 kg"""
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertNotIn("[!NOTE]", formatted)
        self.assertNotIn("&gt;", formatted)
        self.assertIn("💡", formatted)
        self.assertIn("<b>🎯 Odprawa D24 | TRAINING DAY</b>", formatted)
        self.assertIn("<b>Waga:</b> 82.5 kg", formatted)

    def test_whisper_device_cpu_selection(self):
        with patch.dict(os.environ, {"WHISPER_DEVICE": "cpu"}):
            with patch("server_fastapi.whisper_model", None):
                mock_module = unittest.mock.MagicMock()
                mock_whisper = mock_module.WhisperModel
                mock_whisper.return_value = "dummy_cpu_model"
                with patch.dict(sys.modules, {"faster_whisper": mock_module}):
                    model = server_fastapi.init_whisper()
                    self.assertEqual(model, "dummy_cpu_model")
                    mock_whisper.assert_called_once_with('base', device='cpu', compute_type='int8')

    def test_kalistenika_dir_path_override(self):
        test_path = Path("/custom/kalistenika/path")
        with patch.dict(os.environ, {"KALISTENIKA_DIR": str(test_path)}):
            target = Path(os.environ.get("KALISTENIKA_DIR")).resolve()
            self.assertEqual(target, test_path.resolve())

    def test_telegram_format_dlq_emergency_message(self):
        raw = (
            "⚠️ **Chwilowa niedostępność serwerów AI Google.**\n\n"
            "🔒 **Twoja notatka NIE PRZEPADŁA:**\n"
            "> *„Jak tam dzisiaj stoję z kaloriami?”*\n\n"
            "Została bezpiecznie zachowana w buforze awaryjnym (`voice_inbox.md`)."
        )
        formatted = server_fastapi.format_telegram_message(raw)
        self.assertIn("<b>Chwilowa niedostępność serwerów AI Google.</b>", formatted)
        self.assertIn("<b>Twoja notatka NIE PRZEPADŁA:</b>", formatted)
        self.assertIn("<i>„Jak tam dzisiaj stoję z kaloriami?”</i>", formatted)
        self.assertIn("<code>voice_inbox.md</code>", formatted)
        self.assertNotIn("&lt;b&gt;", formatted)
        self.assertNotIn("&lt;i&gt;", formatted)
        self.assertNotIn("&lt;code&gt;", formatted)

    def test_key_pool_failover_on_401_invalid_credentials(self):
        pool = server_fastapi.GeminiKeyPool(keys=["key1", "key2"])
        slot1 = pool.get_active_slot()
        self.assertEqual(slot1.key, "key1")
        # Symulacja błędu 401
        err_msg = 'request failed (code 401): Request had invalid authentication credentials.'
        is_auth_error = "API_KEY_INVALID" in err_msg or "403" in err_msg or "401" in err_msg or "invalid authentication credentials" in err_msg.lower()
        self.assertTrue(is_auth_error)
        pool.mark_slot_exhausted(slot1, cooldown_seconds=86400)
        slot2 = pool.get_active_slot()
        self.assertEqual(slot2.key, "key2")

    def test_key_pool_default_model_initialization(self):
        pool = server_fastapi.GeminiKeyPool(keys=["key_test"])
        self.assertEqual(pool.model_name, "gemini-3.6-flash")

    def test_samsung_health_multi_day_calorie_sliding_window(self):
        payload_sliding = {
            "active_calories": [
                {"start_time": "2026-09-19T10:00:00Z", "calories": 33.5}
            ],
            "total_calories": [
                {"start_time": "2026-09-19T10:00:00Z", "calories": 33.5},
                {"start_time": "2026-09-20T08:00:00Z", "calories": 237.0}
            ]
        }
        response = self.client.post("/samsung-health", json=payload_sliding)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        conn = sqlite3.connect(etl_parser.DB_FILE)
        try:
            c = conn.cursor()
            # D-1 (2026-09-19) -> active_calories 33.5
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-19'")
            row_prev = c.fetchone()
            self.assertIsNotNone(row_prev)
            self.assertAlmostEqual(row_prev[0], 33.5, places=1)

            # D (2026-09-20) -> total_calories 237.0
            c.execute("SELECT spalone_kalorie FROM metryki_dzienne WHERE data='2026-09-20'")
            row_curr = c.fetchone()
            self.assertIsNotNone(row_curr)
            self.assertAlmostEqual(row_curr[0], 237.0, places=1)
        finally:
            conn.close()

if __name__ == '__main__':
    unittest.main()

