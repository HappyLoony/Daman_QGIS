# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_5_4 - Тесты для F_4_4 Feedback + M_38 SessionLogManager.

Тестирует:
- M_38_SessionLogManager - инициализация, запись, ротация, сбор логов
- Fsm_4_4_1_FeedbackDialog - формирование payload, system_info
- API endpoint ?action=feedback - серверная часть (отправка, валидация)
"""

import time
import json
import tempfile
import shutil
from pathlib import Path
from typing import Optional


class FeedbackTests:
    """Тесты системы обратной связи и сессионного логирования."""

    def __init__(self, iface, logger):
        """
        Инициализация теста.

        Args:
            iface: QGIS interface
            logger: TestLogger instance
        """
        self.iface = iface
        self.logger = logger
        self._session = None
        self._temp_dir: Optional[Path] = None

    def _get_session(self):
        """Ленивая инициализация requests session."""
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                pass
        return self._session

    def _create_temp_dir(self) -> Path:
        """Создать временную папку для тестов."""
        if self._temp_dir is None:
            self._temp_dir = Path(tempfile.mkdtemp(prefix="daman_test_m38_"))
        return self._temp_dir

    def _cleanup_temp_dir(self):
        """Удалить временную папку."""
        if self._temp_dir and self._temp_dir.exists():
            try:
                shutil.rmtree(self._temp_dir)
            except Exception:
                pass
            self._temp_dir = None

    def run_all_tests(self):
        """Запуск всех тестов."""
        self.logger.section("ТЕСТ: F_4_4 Feedback + M_38 SessionLogManager")

        try:
            # M_38 тесты
            self.test_m38_import()
            self.test_m38_class_attributes()
            self.test_m38_registry()
            self.test_m38_initialize()
            self.test_m38_write()
            self.test_m38_get_session_logs()
            self.test_m38_rotation()
            self.test_m38_dedup()

            # Fsm_4_4_1 тесты
            self.test_dialog_import()
            self.test_dialog_system_info()
            self.test_dialog_payload_structure()

            # API тесты
            self.test_api_feedback_send()
            self.test_api_feedback_empty_description()
            self.test_api_feedback_anonymous()
            self.test_api_feedback_list()

        except Exception as e:
            self.logger.error(f"Critical error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._cleanup_temp_dir()

        self.logger.summary()

    # ==================== M_38 SessionLogManager тесты ====================

    def test_m38_import(self):
        """Тест импорта SessionLogManager."""
        self.logger.section("M_38: импорт модуля")

        try:
            from Daman_QGIS.managers.infrastructure.M_38_session_log_manager import SessionLogManager
            self.logger.success("SessionLogManager imported")
        except ImportError as e:
            self.logger.fail(f"Import error: {e}")

    def test_m38_class_attributes(self):
        """Тест атрибутов класса SessionLogManager."""
        self.logger.section("M_38: атрибуты класса")

        try:
            from Daman_QGIS.managers.infrastructure.M_38_session_log_manager import SessionLogManager

            mgr = SessionLogManager()

            # Проверяем константы класса
            self.logger.check(
                mgr.LOG_DIR_NAME == "daman_logs",
                "LOG_DIR_NAME = 'daman_logs'",
                f"Wrong LOG_DIR_NAME: {mgr.LOG_DIR_NAME}"
            )

            self.logger.check(
                mgr.MAX_SESSIONS == 3,
                "MAX_SESSIONS = 3",
                f"Wrong MAX_SESSIONS: {mgr.MAX_SESSIONS}"
            )

            self.logger.check(
                mgr.SESSION_PREFIX == "session_",
                "SESSION_PREFIX = 'session_'",
                f"Wrong SESSION_PREFIX: {mgr.SESSION_PREFIX}"
            )

            self.logger.check(
                mgr.CRASH_FILE == "crash_trace.log",
                "CRASH_FILE = 'crash_trace.log'",
                f"Wrong CRASH_FILE: {mgr.CRASH_FILE}"
            )

            # Проверяем _LEVEL_MAP
            from qgis.core import Qgis
            expected_levels = {Qgis.Info, Qgis.Warning, Qgis.Critical, Qgis.Success, Qgis.NoLevel}
            actual_levels = set(mgr._LEVEL_MAP.keys())

            self.logger.check(
                expected_levels == actual_levels,
                f"_LEVEL_MAP covers all {len(expected_levels)} Qgis levels",
                f"Missing levels: {expected_levels - actual_levels}"
            )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_m38_registry(self):
        """Тест что M_38 зарегистрирован в registry."""
        self.logger.section("M_38: регистрация в registry")

        try:
            from Daman_QGIS.managers._registry import registry

            self.logger.check(
                registry.is_registered('M_38'),
                "M_38 registered in registry",
                "M_38 NOT registered in registry!"
            )

            mgr = registry.get('M_38')
            self.logger.check(
                mgr is not None,
                "registry.get('M_38') returns instance",
                "registry.get('M_38') returned None!"
            )

            # Проверяем что это правильный тип
            from Daman_QGIS.managers.infrastructure.M_38_session_log_manager import SessionLogManager
            self.logger.check(
                isinstance(mgr, SessionLogManager),
                "Instance is SessionLogManager",
                f"Wrong type: {type(mgr)}"
            )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_m38_initialize(self):
        """Тест инициализации M_38 (активный экземпляр)."""
        self.logger.section("M_38: инициализация")

        try:
            from Daman_QGIS.managers._registry import registry
            mgr = registry.get('M_38')

            # Проверяем что менеджер инициализирован (из main_plugin.py)
            self.logger.check(
                mgr._initialized,
                "Manager is initialized",
                "Manager is NOT initialized!"
            )

            # Проверяем что есть лог-файл
            self.logger.check(
                mgr._log_file is not None and mgr._log_file.exists(),
                f"Log file exists: {mgr._log_file}",
                f"Log file missing: {mgr._log_file}"
            )

            # Проверяем session_id
            session_id = mgr.get_session_id()
            self.logger.check(
                session_id is not None and session_id.startswith("session_"),
                f"Session ID: {session_id}",
                f"Invalid session ID: {session_id}"
            )

            # Проверяем log_dir
            log_dir = mgr.get_log_dir()
            self.logger.check(
                log_dir is not None and log_dir.exists(),
                f"Log dir exists: {log_dir}",
                f"Log dir missing: {log_dir}"
            )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_m38_write(self):
        """Тест записи в лог."""
        self.logger.section("M_38: запись в лог")

        try:
            from Daman_QGIS.managers._registry import registry
            mgr = registry.get('M_38')

            if not mgr._initialized:
                self.logger.skip("Manager not initialized")
                return

            # Записываем тестовое сообщение
            test_msg = f"TEST_MARKER_{int(time.time())}"
            mgr.write(test_msg, tag="TEST", level="INFO")

            # Flush и проверяем файл
            if mgr._file_handler:
                mgr._file_handler.flush()

            # Читаем файл и ищем наше сообщение
            content = mgr._log_file.read_text(encoding='utf-8')

            self.logger.check(
                test_msg in content,
                "Test message written to log file",
                "Test message NOT found in log file!"
            )

            self.logger.check(
                "[TEST]" in content,
                "Tag [TEST] present in log",
                "Tag [TEST] not found in log"
            )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_m38_get_session_logs(self):
        """Тест get_session_logs()."""
        self.logger.section("M_38: get_session_logs")

        try:
            from Daman_QGIS.managers._registry import registry
            mgr = registry.get('M_38')

            if not mgr._initialized:
                self.logger.skip("Manager not initialized")
                return

            logs = mgr.get_session_logs(max_lines=100)

            self.logger.check(
                isinstance(logs, list),
                f"Returns list, length: {len(logs)}",
                f"Wrong type: {type(logs)}"
            )

            self.logger.check(
                len(logs) > 0,
                f"At least 1 session log available",
                "No session logs available!"
            )

            if logs:
                # Проверяем структуру первого элемента
                first = logs[0]
                self.logger.check(
                    "session_id" in first and "content" in first,
                    "Log entry has session_id and content keys",
                    f"Missing keys: {list(first.keys())}"
                )

                self.logger.check(
                    first["session_id"].startswith("session_") or first["session_id"] == "crash_trace",
                    f"Valid session_id: {first['session_id']}",
                    f"Invalid session_id: {first['session_id']}"
                )

                self.logger.check(
                    len(first["content"]) > 0,
                    f"Content not empty ({len(first['content'])} chars)",
                    "Content is empty!"
                )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_m38_rotation(self):
        """Тест ротации сессий (на отдельном экземпляре)."""
        self.logger.section("M_38: ротация сессий")

        try:
            temp_dir = self._create_temp_dir()
            log_dir = temp_dir / "daman_logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            # Создаём 5 фейковых сессий
            for i in range(5):
                fake_file = log_dir / f"session_2026-02-1{i}_10-00-00.log"
                fake_file.write_text(f"Fake session {i}\n", encoding='utf-8')

            from Daman_QGIS.managers.infrastructure.M_38_session_log_manager import SessionLogManager
            mgr = SessionLogManager()
            mgr._log_dir = log_dir

            # Запускаем ротацию
            mgr._rotate_sessions()

            # Проверяем: должно остаться MAX_SESSIONS - 1 = 2 файла
            remaining = list(log_dir.glob("session_*.log"))

            self.logger.check(
                len(remaining) == mgr.MAX_SESSIONS - 1,
                f"After rotation: {len(remaining)} files (expected {mgr.MAX_SESSIONS - 1})",
                f"After rotation: {len(remaining)} files (expected {mgr.MAX_SESSIONS - 1})!"
            )

            # Проверяем что остались самые новые
            remaining_names = sorted([f.name for f in remaining])
            self.logger.check(
                "session_2026-02-14_10-00-00.log" in remaining_names,
                "Newest session preserved",
                f"Unexpected files: {remaining_names}"
            )

            self.logger.check(
                "session_2026-02-13_10-00-00.log" in remaining_names,
                "Second newest session preserved",
                f"Unexpected files: {remaining_names}"
            )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_m38_dedup(self):
        """Тест дедупликации: сообщения от PLUGIN_NAME пропускаются в _on_message_received."""
        self.logger.section("M_38: дедупликация (PLUGIN_NAME filter)")

        try:
            from Daman_QGIS.managers._registry import registry
            from Daman_QGIS.constants import PLUGIN_NAME
            from qgis.core import Qgis

            mgr = registry.get('M_38')

            if not mgr._initialized:
                self.logger.skip("Manager not initialized")
                return

            # Запоминаем текущий размер файла
            initial_size = mgr._log_file.stat().st_size

            # Вызываем _on_message_received с нашим тегом -- должен быть пропущен
            mgr._on_message_received("DEDUP_TEST_MSG", PLUGIN_NAME, Qgis.Info)

            # Flush
            if mgr._file_handler:
                mgr._file_handler.flush()

            new_size = mgr._log_file.stat().st_size

            self.logger.check(
                new_size == initial_size,
                "PLUGIN_NAME messages correctly skipped in _on_message_received",
                f"Message was NOT skipped! Size grew: {initial_size} -> {new_size}"
            )

            # Теперь с тегом Python + Warning -- должен быть записан
            mgr._on_message_received("DEDUP_OTHER_TAG_TEST", "Python", Qgis.Warning)

            if mgr._file_handler:
                mgr._file_handler.flush()

            final_size = mgr._log_file.stat().st_size

            self.logger.check(
                final_size > new_size,
                "Non-PLUGIN_NAME messages correctly written",
                "Non-PLUGIN_NAME message was not written!"
            )

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    # ==================== Fsm_4_4_1 Dialog тесты ====================

    def test_dialog_import(self):
        """Тест импорта FeedbackDialog."""
        self.logger.section("Fsm_4_4_1: импорт модуля")

        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_4_1_feedback_dialog import FeedbackDialog
            self.logger.success("FeedbackDialog imported")

            # Проверяем константы
            self.logger.check(
                FeedbackDialog.MIN_DESCRIPTION_LENGTH == 10,
                "MIN_DESCRIPTION_LENGTH = 10",
                f"Wrong: {FeedbackDialog.MIN_DESCRIPTION_LENGTH}"
            )

            self.logger.check(
                FeedbackDialog.MAX_LOG_LINES == 500,
                "MAX_LOG_LINES = 500",
                f"Wrong: {FeedbackDialog.MAX_LOG_LINES}"
            )

        except ImportError as e:
            self.logger.fail(f"Import error: {e}")

    def test_dialog_system_info(self):
        """Тест _collect_system_info."""
        self.logger.section("Fsm_4_4_1: system_info")

        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_4_1_feedback_dialog import FeedbackDialog

            # Создаём диалог (без показа)
            dialog = FeedbackDialog(self.iface)

            info = dialog._collect_system_info()

            required_fields = ['v', 'qgis', 'os', 'py']
            for field in required_fields:
                self.logger.check(
                    field in info,
                    f"Field '{field}' present: {info.get(field, '?')}",
                    f"Field '{field}' missing!"
                )

            # Проверяем что os - одно из допустимых значений
            self.logger.check(
                info.get('os') in ('win', 'linux', 'mac', 'unknown'),
                f"OS type valid: {info.get('os')}",
                f"Invalid OS type: {info.get('os')}"
            )

            # Закрываем диалог
            dialog.close()
            dialog.deleteLater()

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    def test_dialog_payload_structure(self):
        """Тест структуры payload."""
        self.logger.section("Fsm_4_4_1: структура payload")

        try:
            from Daman_QGIS.tools.F_4_plagin.submodules.Fsm_4_4_1_feedback_dialog import FeedbackDialog

            dialog = FeedbackDialog(self.iface)

            # Заполняем поля
            dialog.description_edit.setPlainText("Test feedback description for testing")
            dialog.email_input.setText("test@example.com")

            # Проверяем что описание считывается
            description = dialog.description_edit.toPlainText().strip()
            self.logger.check(
                len(description) >= dialog.MIN_DESCRIPTION_LENGTH,
                f"Description valid ({len(description)} chars)",
                f"Description too short: {len(description)}"
            )

            # Проверяем что email считывается
            email = dialog.email_input.text().strip()
            self.logger.check(
                email == "test@example.com",
                "Email field readable",
                f"Email mismatch: {email}"
            )

            # Проверяем system_info
            info = dialog._collect_system_info()
            self.logger.check(
                isinstance(info, dict) and len(info) >= 4,
                f"system_info has {len(info)} fields",
                "system_info incomplete"
            )

            dialog.close()
            dialog.deleteLater()

        except Exception as e:
            self.logger.fail(f"Error: {e}")

    # ==================== API тесты ====================

    def test_api_feedback_send(self):
        """Тест отправки feedback через API."""
        self.logger.section("API: отправка feedback")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=feedback"
        payload = {
            "uid": "DAMAN-TEST-FEED-XXXX",
            "hardware_id": "TEST-HARDWARE-FEEDBACK",
            "description": "Automated test feedback from Fsm_4_2_T_5_4",
            "email": "",
            "system_info": {
                "v": "0.9.999",
                "qgis": "3.40.1",
                "os": "win",
                "py": "3.12"
            },
            "session_logs": [
                {
                    "session_id": "session_test_2026-02-17",
                    "content": "Test log line 1\nTest log line 2\n"
                }
            ]
        }

        try:
            start = time.time()
            response = session.post(url, json=payload, timeout=API_TIMEOUT)
            elapsed = time.time() - start

            self.logger.check(
                response.status_code == 200,
                f"HTTP 200 OK ({elapsed:.2f}s)",
                f"HTTP {response.status_code}: {response.text[:200]}"
            )

            if response.status_code == 200:
                data = response.json()

                self.logger.check(
                    data.get("status") == "success",
                    "Status: success",
                    f"Unexpected status: {data}"
                )

                self.logger.check(
                    "feedback_id" in data,
                    f"Feedback ID: {data.get('feedback_id')}",
                    "Missing feedback_id in response!"
                )

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_feedback_empty_description(self):
        """Тест ошибки при пустом описании."""
        self.logger.section("API: ошибка при пустом описании")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=feedback"
        payload = {
            "uid": "DAMAN-TEST-EMPTY-DESC",
            "description": "",
            "system_info": {}
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            self.logger.check(
                response.status_code == 400,
                f"Correctly rejected empty description (HTTP {response.status_code})",
                f"Expected 400, got {response.status_code}"
            )

            if response.status_code == 400:
                data = response.json()
                self.logger.check(
                    data.get("error_code") == "MISSING_DESCRIPTION",
                    f"Error code: MISSING_DESCRIPTION",
                    f"Unexpected error code: {data.get('error_code')}"
                )

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_feedback_anonymous(self):
        """Тест отправки feedback без UID (anonymous)."""
        self.logger.section("API: feedback от anonymous")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=feedback"
        payload = {
            "uid": "anonymous",
            "hardware_id": "unknown",
            "description": "Test anonymous feedback from automated tests",
            "system_info": {"v": "test", "qgis": "test", "os": "test", "py": "test"}
        }

        try:
            response = session.post(url, json=payload, timeout=API_TIMEOUT)

            self.logger.check(
                response.status_code == 200,
                "Anonymous feedback accepted (HTTP 200)",
                f"Unexpected: HTTP {response.status_code}"
            )

            if response.status_code == 200:
                data = response.json()
                self.logger.check(
                    data.get("status") == "success",
                    "Anonymous feedback saved",
                    f"Unexpected: {data}"
                )

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")

    def test_api_feedback_list(self):
        """Тест получения списка feedback (без admin key -- должен вернуть 403)."""
        self.logger.section("API: feedback_list без ключа")

        try:
            from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT
        except ImportError:
            self.logger.skip("constants не доступны")
            return

        session = self._get_session()
        if not session:
            self.logger.skip("requests library not available")
            return

        url = f"{API_BASE_URL}?action=feedback_list&key=WRONG_KEY&days=1"

        try:
            response = session.get(url, timeout=API_TIMEOUT)

            self.logger.check(
                response.status_code == 403,
                "Correctly rejected wrong admin key (HTTP 403)",
                f"Expected 403, got {response.status_code}"
            )

        except Exception as e:
            self.logger.fail(f"Request failed: {e}")
