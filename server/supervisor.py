import os
import sys

# Ochrona przed srodowiskiem bezokienkowym pythonw.exe (gdzie sys.stdout/stderr moga byc None na Windows)
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import time
import signal
import argparse
import datetime
import subprocess
from pathlib import Path
from typing import Optional, List

BASE_DIR = Path(__file__).resolve().parent

kalistenika_env = os.environ.get("KALISTENIKA_DIR")
if kalistenika_env:
    WORKSPACE_DIR = Path(kalistenika_env).resolve()
else:
    WORKSPACE_DIR = BASE_DIR.parent.parent / "kalistenika"

DEFAULT_LOG_FILE = WORKSPACE_DIR / "server_log.txt"


def log_supervisor(message: str, log_file: Optional[Path] = None) -> None:
    target_log = log_file if log_file is not None else DEFAULT_LOG_FILE
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{now_str}] [SUPERVISOR] {message}\n"

    try:
        sys.stdout.write(entry)
        sys.stdout.flush()
    except Exception:
        pass

    try:
        target_log.parent.mkdir(parents=True, exist_ok=True)
        with open(target_log, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        try:
            sys.stderr.write(f"Blad zapisu logu supervisora: {e}\n")
        except Exception:
            pass


class ProcessSupervisor:
    """Natywny, zdarzeniowy nadzorca procesu (Event-Driven Kernel Supervisor)

    z mechanizmem Anti-Flapping i bezpiecznym wygaszaniem (Graceful Shutdown).
    """

    def __init__(
        self,
        target_script: Path,
        python_executable: Optional[str] = None,
        delay: float = 2.0,
        max_restarts: Optional[int] = None,
        log_file: Optional[Path] = None,
        flap_threshold_sec: float = 5.0,
        flap_count_threshold: int = 5,
        base_flap_delay: float = 15.0,
        max_flap_delay: float = 30.0,
    ):
        self.target_script = Path(target_script).resolve()
        self.python_executable = python_executable or sys.executable
        self.delay = max(0.0, float(delay))
        self.max_restarts = max_restarts
        self.log_file = Path(log_file).resolve() if log_file else None
        self.flap_threshold_sec = float(flap_threshold_sec)
        self.flap_count_threshold = int(flap_count_threshold)
        self.base_flap_delay = float(base_flap_delay)
        self.max_flap_delay = float(max_flap_delay)

        self.stop_requested = False
        self.current_process: Optional[subprocess.Popen] = None
        self.consecutive_flaps = 0
        self.restarts_done = 0

    def _setup_signal_handlers(self) -> None:
        def _handler(sig, frame):
            self.stop()

        try:
            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, _handler)
        except (ValueError, AttributeError):
            # Ignoruj brak mozliwosci podpiecia sygnalu (np. w watkach podrzednych podczas testow)
            pass

    def stop(self) -> None:
        """Sygnalizuje zadanie zatrzymania nadzorcy i natychmiast zamyka proces potomny."""
        self.stop_requested = True
        self.terminate_child()

    def terminate_child(self, timeout: float = 5.0) -> None:
        """Bezpieczne zamykanie procesu potomnego (Graceful Shutdown -> Kill fallback)."""
        proc = self.current_process
        if proc is not None and proc.poll() is None:
            log_supervisor(
                f"Wysylanie sygnalu zakonczenia do procesu potomnego (PID: {proc.pid})...",
                self.log_file,
            )
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log_supervisor(
                    f"Proces potomny (PID: {proc.pid}) nie odpowiedzial na terminate w czasie {timeout}s. Wymuszanie kill...",
                    self.log_file,
                )
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
            except Exception as e:
                log_supervisor(f"Wyjatek podczas zamykania procesu potomnego: {e}", self.log_file)

    def calculate_delay(self, uptime: float) -> float:
        """Oblicza czas pauzy przed restartem z uwzglednieniem zabezpieczenia Anti-Flapping."""
        if uptime < self.flap_threshold_sec:
            self.consecutive_flaps += 1
        else:
            self.consecutive_flaps = 0

        if self.consecutive_flaps >= self.flap_count_threshold:
            multiplier = 2 ** (self.consecutive_flaps - self.flap_count_threshold)
            calculated = min(self.max_flap_delay, self.base_flap_delay * multiplier)
            delay_repr = f"{calculated:g}"
            log_supervisor(
                f"OSTRZEZENIE: Wykryto serie {self.consecutive_flaps} awarii w czasie < {self.flap_threshold_sec}s (Anti-Flapping). Wydluzenie pauzy do {delay_repr}s.",
                self.log_file,
            )
            return calculated

        return self.delay

    def run(self) -> int:
        """Glowna petla nadzorcy oparta na zdarzeniach jadra (process.wait)."""
        self._setup_signal_handlers()
        log_supervisor(
            f"Nadzorca procesu uruchomiony. Cel: {self.target_script}",
            self.log_file,
        )

        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        while not self.stop_requested:
            start_time = time.monotonic()

            try:
                self.current_process = subprocess.Popen(
                    [self.python_executable, str(self.target_script)],
                    cwd=str(self.target_script.parent),
                    creationflags=creation_flags,
                )
            except Exception as e:
                log_supervisor(
                    f"Blad uruchamiania procesu potomnego: {e}. Ponowna proba za {self.delay}s...",
                    self.log_file,
                )
                if self.max_restarts is not None and self.restarts_done >= self.max_restarts:
                    break
                self.restarts_done += 1
                time.sleep(self.delay)
                continue

            child_pid = self.current_process.pid
            log_supervisor(
                f"Uruchomiono proces potomny (PID: {child_pid}). Czuwanie nadzorcze aktywne.",
                self.log_file,
            )

            try:
                exit_code = self.current_process.wait()
            except KeyboardInterrupt:
                self.stop_requested = True
                self.terminate_child()
                log_supervisor(
                    "Nadzorca zatrzymany sygnalem klawiatury (KeyboardInterrupt).",
                    self.log_file,
                )
                break

            if self.stop_requested:
                log_supervisor(
                    f"Nadzorca zatrzymany na zadanie. Proces potomny zakonczony (PID: {child_pid}, kod: {exit_code}).",
                    self.log_file,
                )
                break

            uptime = time.monotonic() - start_time
            current_delay = self.calculate_delay(uptime)
            delay_repr = f"{current_delay:g}"

            if self.max_restarts is not None and self.restarts_done >= self.max_restarts:
                log_supervisor(
                    f"Wykryto zakonczenie serwera (PID: {child_pid}, kod wyjscia: {exit_code}). Osiagnieto limit restartow ({self.max_restarts}). Zakonczenie pracy nadzorcy.",
                    self.log_file,
                )
                break

            # Format scisle wg SPEC-002:
            # [YYYY-MM-DD HH:MM:SS] [SUPERVISOR] Wykryto zakonczenie serwera (PID: {pid}, kod wyjscia: {code}). Automatyczne wznowienie za {delay}s...
            log_supervisor(
                f"Wykryto zakonczenie serwera (PID: {child_pid}, kod wyjscia: {exit_code}). Automatyczne wznowienie za {delay_repr}s...",
                self.log_file,
            )

            self.restarts_done += 1

            # Odliczanie z natychmiastowa reakcja na flage stop_requested
            slept = 0.0
            while slept < current_delay and not self.stop_requested:
                step = min(0.1, current_delay - slept)
                time.sleep(step)
                slept += step

        log_supervisor("Nadzorca zakonczyl dzialanie pomyslnie.", self.log_file)
        return 0


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Natywny Nadzorca Procesu (Native Process Supervisor) dla Project Coach"
    )
    parser.add_argument(
        "--target-script",
        type=str,
        default=str(BASE_DIR / "server_fastapi.py"),
        help="Sciezka do nadzorowanego skryptu Pythona (domyslnie: server_fastapi.py)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Czas pauzy przed restartem w sekundach (domyslnie: 2.0)",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=None,
        help="Maksymalna liczba restartow (domyslnie: brak limitu)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Uruchom tylko jeden cykl restartu (odpowiednik --max-restarts 1)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Opcjonalna sciezka do wlasnego pliku logu",
    )
    parser.add_argument(
        "--flap-threshold-sec",
        type=float,
        default=5.0,
        help="Prog czasu zycia procesu dla anti-flapping w sekundach (domyslnie: 5.0)",
    )
    parser.add_argument(
        "--flap-count",
        type=int,
        default=5,
        help="Liczba szybkich awarii aktywujacych anti-flapping (domyslnie: 5)",
    )
    return parser.parse_args(args)


def main():
    args = parse_args()
    max_restarts = 1 if args.once else args.max_restarts
    log_file = Path(args.log_file).resolve() if args.log_file else None

    supervisor = ProcessSupervisor(
        target_script=Path(args.target_script).resolve(),
        delay=args.delay,
        max_restarts=max_restarts,
        log_file=log_file,
        flap_threshold_sec=args.flap_threshold_sec,
        flap_count_threshold=args.flap_count,
    )
    sys.exit(supervisor.run())


if __name__ == "__main__":
    main()
