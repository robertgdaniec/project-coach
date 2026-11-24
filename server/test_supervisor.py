import os
import sys
import time
import re
import shutil
import tempfile
import threading
from pathlib import Path
import pytest

from supervisor import ProcessSupervisor, parse_args, log_supervisor


class TestProcessSupervisor:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.test_dir = tempfile.mkdtemp()
        self.log_file = Path(self.test_dir) / "test_supervisor_log.txt"
        self.mock_script = Path(self.test_dir) / "mock_child.py"
        yield
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cli_parsing_defaults_and_custom(self):
        # Domyslne wartosci
        args = parse_args([])
        assert args.delay == 2.0
        assert args.max_restarts is None
        assert args.once is False
        assert args.flap_threshold_sec == 5.0
        assert args.flap_count == 5
        assert "server_fastapi.py" in args.target_script

        # Flagi wlasne
        custom_args = parse_args([
            "--target-script", "custom_target.py",
            "--delay", "0.5",
            "--max-restarts", "3",
            "--log-file", "custom_log.txt",
            "--flap-threshold-sec", "2.5",
            "--flap-count", "4"
        ])
        assert custom_args.target_script == "custom_target.py"
        assert custom_args.delay == 0.5
        assert custom_args.max_restarts == 3
        assert custom_args.log_file == "custom_log.txt"
        assert custom_args.flap_threshold_sec == 2.5
        assert custom_args.flap_count == 4

        # Flaga --once
        once_args = parse_args(["--once"])
        assert once_args.once is True

    def test_supervisor_restarts_crashing_child_and_logs(self):
        # Skrypt mockowy konczacy sie kodem 42
        self.mock_script.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")

        supervisor = ProcessSupervisor(
            target_script=self.mock_script,
            delay=0.05,
            max_restarts=2,
            log_file=self.log_file
        )

        exit_code = supervisor.run()
        assert exit_code == 0
        assert supervisor.restarts_done == 2

        assert self.log_file.exists()
        log_content = self.log_file.read_text(encoding="utf-8")

        # Weryfikacja scislego formatu logu zgodnie ze SPEC-002:
        # [YYYY-MM-DD HH:MM:SS] [SUPERVISOR] Wykryto zakonczenie serwera (PID: {pid}, kod wyjscia: {code}). Automatyczne wznowienie za {delay}s...
        pattern = r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[SUPERVISOR\] Wykryto zakonczenie serwera \(PID: \d+, kod wyjscia: 42\)\. Automatyczne wznowienie za [\d\.]+s\.\.\."
        matches = re.findall(pattern, log_content)
        assert len(matches) == 2, f"Oczekiwano 2 dopasowan scislego formatu, znaleziono: {len(matches)}. Log:\n{log_content}"

    def test_supervisor_default_delay_integer_formatting(self):
        # Sprawdzenie, ze domyslny delay 2.0 loguje sie jako calkowita wartosc "2s..." zgodnie ze SPEC
        self.mock_script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        supervisor = ProcessSupervisor(
            target_script=self.mock_script,
            delay=2.0,
            max_restarts=1,
            log_file=self.log_file
        )
        supervisor.run()
        log_content = self.log_file.read_text(encoding="utf-8")
        assert "Automatyczne wznowienie za 2s..." in log_content

    def test_supervisor_anti_flapping_backoff(self):
        # Skrypt natychmiastowo crashujacy
        self.mock_script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")

        # Ustawiamy prog 3 awarii, base_flap_delay=0.1s
        supervisor = ProcessSupervisor(
            target_script=self.mock_script,
            delay=0.01,
            max_restarts=4,
            log_file=self.log_file,
            flap_threshold_sec=2.0,
            flap_count_threshold=3,
            base_flap_delay=0.1,
            max_flap_delay=0.2
        )

        exit_code = supervisor.run()
        assert exit_code == 0
        assert supervisor.restarts_done == 4

        log_content = self.log_file.read_text(encoding="utf-8")
        assert "OSTRZEZENIE: Wykryto serie 3 awarii w czasie < 2.0s (Anti-Flapping)" in log_content
        assert "OSTRZEZENIE: Wykryto serie 4 awarii w czasie < 2.0s (Anti-Flapping)" in log_content

    def test_supervisor_graceful_shutdown(self):
        # Dlugodzialajacy skrypt potomny
        self.mock_script.write_text(
            "import time\n"
            "try:\n"
            "    while True:\n"
            "        time.sleep(0.1)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n",
            encoding="utf-8"
        )

        supervisor = ProcessSupervisor(
            target_script=self.mock_script,
            delay=0.5,
            log_file=self.log_file
        )

        supervisor_thread = threading.Thread(target=supervisor.run, daemon=True)
        supervisor_thread.start()

        # Oczekiwanie na uruchomienie procesu potomnego
        started = False
        child_proc = None
        for _ in range(50):
            if supervisor.current_process is not None and supervisor.current_process.poll() is None:
                child_proc = supervisor.current_process
                started = True
                break
            time.sleep(0.05)

        assert started, "Proces potomny nie wystartowal w oczekiwanym czasie"
        assert child_proc is not None

        # Zatrzymanie nadzorcy
        supervisor.stop()
        supervisor_thread.join(timeout=5.0)

        assert not supervisor_thread.is_alive(), "Watek nadzorcy nie zakonczyl sie w zadanym czasie"
        assert child_proc.poll() is not None, "Proces potomny nie zostal zterminowany"

        log_content = self.log_file.read_text(encoding="utf-8")
        assert "Nadzorca zatrzymany na zadanie" in log_content or "Wysylanie sygnalu zakonczenia" in log_content

    def test_calculate_delay_progression(self):
        supervisor = ProcessSupervisor(
            target_script=self.mock_script,
            delay=2.0,
            flap_threshold_sec=5.0,
            flap_count_threshold=5,
            base_flap_delay=15.0,
            max_flap_delay=30.0,
            log_file=self.log_file
        )

        # 4 awarie ponizej progu -> nadal normalny delay
        for _ in range(4):
            assert supervisor.calculate_delay(1.0) == 2.0

        # 5 awaria -> aktywacja anti-flapping (15.0s)
        assert supervisor.calculate_delay(1.0) == 15.0

        # 6 awaria -> 30.0s (max_flap_delay)
        assert supervisor.calculate_delay(1.0) == 30.0

        # Uptime > 5.0s -> reset licznika flappingu
        assert supervisor.calculate_delay(6.0) == 2.0
        assert supervisor.consecutive_flaps == 0
