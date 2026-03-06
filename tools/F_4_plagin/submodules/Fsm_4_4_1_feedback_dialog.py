# -*- coding: utf-8 -*-
"""
Fsm_4_4_1_FeedbackDialog - GUI диалог обратной связи

Интерфейс для:
- Ввода описания проблемы/предложения
- Указания email (опционально)
- Автоматического прикрепления логов последних 3 сессий
- Отправки через Yandex Cloud API (action=feedback)
"""

import sys
import platform
import threading
from typing import Optional, Dict, Any

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QGroupBox, QMessageBox
)
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis

from Daman_QGIS.constants import API_BASE_URL, API_TIMEOUT, PLUGIN_VERSION
from Daman_QGIS.utils import log_info, log_error, log_warning


class FeedbackDialog(QDialog):
    """Диалог обратной связи"""

    # Минимальная длина описания
    MIN_DESCRIPTION_LENGTH = 10

    # Максимум строк из каждого лог-файла сессии
    MAX_LOG_LINES = 500

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        self.setWindowTitle("Daman_QGIS - Обратная связь")
        self.setMinimumWidth(550)
        self.setMinimumHeight(450)

        self.setup_ui()
        self._prefill_email()

    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Заголовок
        title_label = QLabel("Обратная связь - Daman QGIS")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Описание
        desc_label = QLabel("Опишите проблему или предложение.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666;")
        layout.addWidget(desc_label)

        # Группа описания проблемы
        description_group = self._create_description_group()
        layout.addWidget(description_group)

        # Группа контактной информации
        contact_group = self._create_contact_group()
        layout.addWidget(contact_group)

        # Разделитель
        layout.addStretch()

        # Кнопки
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.send_btn = QPushButton("Отправить")
        self.send_btn.clicked.connect(self.on_send)
        self.send_btn.setMinimumWidth(120)
        button_layout.addWidget(self.send_btn)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # Статусная строка
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _create_description_group(self) -> QGroupBox:
        """Создание группы описания проблемы"""
        group = QGroupBox("Описание проблемы")
        layout = QVBoxLayout(group)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Опишите проблему или предложение...\n\n"
            "Укажите:\n"
            "- Что вы делали\n"
            "- Что ожидали\n"
            "- Что произошло"
        )
        self.description_edit.setMinimumHeight(120)
        layout.addWidget(self.description_edit)

        return group

    def _create_contact_group(self) -> QGroupBox:
        """Создание группы контактной информации"""
        group = QGroupBox("Контактная информация (опционально)")
        layout = QHBoxLayout(group)

        layout.addWidget(QLabel("Email:"))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your@email.com")
        layout.addWidget(self.email_input)

        return group


    def showEvent(self, event):
        """Очистка при каждом открытии диалога."""
        super().showEvent(event)
        self.description_edit.clear()
        self.status_label.setText("")
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Отправить")

    def _prefill_email(self):
        """Подставить email из лицензии (если есть)."""
        try:
            from Daman_QGIS.managers import registry
            license_mgr = registry.get('M_29')
            email = license_mgr.get_user_email()
            if email:
                self.email_input.setText(email)
        except Exception:
            pass

    def on_send(self):
        """Обработка нажатия кнопки Отправить"""
        log_info("Fsm_4_4_1: on_send() вызван")
        description = self.description_edit.toPlainText().strip()

        # Валидация
        if len(description) < self.MIN_DESCRIPTION_LENGTH:
            self.status_label.setText(
                f"Описание слишком короткое (минимум {self.MIN_DESCRIPTION_LENGTH} символов)"
            )
            self.status_label.setStyleSheet("color: red;")
            return

        # Собираем ВСЕ данные из GUI до запуска потока (thread safety)
        email = self.email_input.text().strip()
        log_info(f"Fsm_4_4_1: GUI данные собраны: desc={len(description)} chars, "
                 f"email={'yes' if email else 'no'}")

        # Блокируем кнопку
        self.send_btn.setEnabled(False)
        self.send_btn.setText("Отправка...")
        self.status_label.setText("Отправка...")
        self.status_label.setStyleSheet("color: #666;")

        # Отправляем в отдельном потоке чтобы не блокировать UI
        log_info("Fsm_4_4_1: Запуск фонового потока отправки")
        thread = threading.Thread(
            target=self._send_feedback_thread,
            args=(description, email),
            daemon=True
        )
        thread.start()
        log_info(f"Fsm_4_4_1: Поток запущен: {thread.name}")

    def _send_feedback_thread(self, description: str, email: str):
        """Отправка feedback в отдельном потоке."""
        log_info(f"Fsm_4_4_1: _send_feedback_thread НАЧАЛО (thread={threading.current_thread().name})")
        try:
            success, message = self._send_feedback(description, email)
            log_info(f"Fsm_4_4_1: _send_feedback вернул: success={success}, message={message[:100]}")

            from qgis.PyQt.QtCore import QTimer

            if success:
                log_info("Fsm_4_4_1: Планируем QTimer.singleShot -> _on_send_success")
                QTimer.singleShot(0, lambda: self._on_send_success(message))
            else:
                log_info("Fsm_4_4_1: Планируем QTimer.singleShot -> _on_send_error")
                QTimer.singleShot(0, lambda: self._on_send_error(message))

            log_info("Fsm_4_4_1: _send_feedback_thread КОНЕЦ (QTimer запланирован)")

        except Exception as e:
            log_error(f"Fsm_4_4_1: _send_feedback_thread ИСКЛЮЧЕНИЕ: {type(e).__name__}: {e}")
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._on_send_error(str(e)))

    def _on_send_success(self, message: str):
        """Обработка успешной отправки (в основном потоке)."""
        log_info(f"Fsm_4_4_1: _on_send_success вызван (thread={threading.current_thread().name})")

        QMessageBox.information(
            self,
            "Обратная связь",
            "Сообщение отправлено."
        )

        log_info("Fsm_4_4_1: Feedback отправлен, закрытие диалога")
        self.accept()

    def _on_send_error(self, error_message: str):
        """Обработка ошибки отправки (в основном потоке)."""
        log_info(f"Fsm_4_4_1: _on_send_error вызван (thread={threading.current_thread().name})")
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Отправить")

        self.status_label.setText(f"Ошибка: {error_message}")
        self.status_label.setStyleSheet("color: red;")

        QMessageBox.critical(
            self,
            "Ошибка отправки",
            f"Не удалось отправить обратную связь:\n{error_message}\n\n"
            "Попробуйте позже."
        )

        log_error(f"Fsm_4_4_1: Ошибка отправки feedback: {error_message}")

    def _send_feedback(self, description: str, email: str) -> tuple:
        """
        Формирование и отправка payload.

        Args:
            description: Текст описания от пользователя
            email: Email пользователя (прочитан из GUI в main thread)

        Returns:
            (success: bool, message: str)
        """
        import time as _time
        t0 = _time.time()

        log_info("Fsm_4_4_1: _send_feedback НАЧАЛО")

        try:
            log_info("Fsm_4_4_1: Импорт requests...")
            import requests
            log_info("Fsm_4_4_1: requests импортирован")
        except ImportError:
            return False, "Библиотека requests не установлена"

        # system_info не содержит GUI-виджетов, безопасно из любого потока
        log_info("Fsm_4_4_1: Сбор system_info...")
        system_info = self._collect_system_info()
        log_info(f"Fsm_4_4_1: system_info собран: {system_info}")

        # UID и Hardware ID (если есть лицензия)
        uid = "anonymous"
        hardware_id = "unknown"
        log_info("Fsm_4_4_1: Получение uid/hardware_id из лицензии...")
        try:
            from Daman_QGIS.managers import registry
            license_mgr = registry.get('M_29')
            log_info("Fsm_4_4_1: LicenseManager получен, запрос api_key...")
            api_key = license_mgr.get_api_key()
            if api_key:
                uid = api_key
            log_info(f"Fsm_4_4_1: api_key={'set' if api_key else 'none'}, запрос hardware_id...")
            hw_id = license_mgr.get_hardware_id()
            if hw_id:
                hardware_id = hw_id
            log_info(f"Fsm_4_4_1: hardware_id={'set' if hw_id else 'none'}")
        except Exception as e:
            log_warning(f"Fsm_4_4_1: Ошибка получения лицензии: {type(e).__name__}: {e}")

        t1 = _time.time()
        log_info(f"Fsm_4_4_1: Сбор system_info + uid: {t1 - t0:.2f}s")

        # Логи сессий прикрепляются всегда
        session_logs = []
        log_info("Fsm_4_4_1: Сбор логов сессий...")
        try:
            from Daman_QGIS.managers._registry import registry
            session_log = registry.get('M_38')
            log_info(f"Fsm_4_4_1: M_38 получен, initialized={session_log._initialized}, "
                     f"вызов get_session_logs(max_lines={self.MAX_LOG_LINES})...")
            session_logs = session_log.get_session_logs(max_lines=self.MAX_LOG_LINES)
            log_info(f"Fsm_4_4_1: get_session_logs вернул {len(session_logs)} записей")
        except Exception as e:
            log_warning(f"Fsm_4_4_1: Не удалось собрать логи: {type(e).__name__}: {e}")

        t2 = _time.time()
        logs_size = sum(len(l.get("content", "")) for l in session_logs)
        log_info(f"Fsm_4_4_1: Сбор логов: {t2 - t1:.2f}s, "
                 f"сессий: {len(session_logs)}, размер: {logs_size / 1024:.0f} KB")

        # Формируем payload
        log_info("Fsm_4_4_1: Формирование payload...")
        payload = {
            "uid": uid,
            "hardware_id": hardware_id,
            "description": description,
            "email": email,
            "system_info": system_info,
            "session_logs": session_logs
        }

        # Проверяем размер payload (лимит ~1MB для Yandex Cloud Function)
        import json
        log_info("Fsm_4_4_1: Сериализация payload для проверки размера...")
        payload_json = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        payload_size = len(payload_json)
        log_info(f"Fsm_4_4_1: Payload: {payload_size / 1024:.0f} KB")

        if payload_size > 900_000:  # 900KB с запасом
            # Первая попытка: обрезаем логи до 200 строк
            for log_entry in session_logs:
                content = log_entry.get("content", "")
                lines = content.split('\n')
                if len(lines) > 200:
                    log_entry["content"] = '\n'.join(lines[-200:])

            payload["session_logs"] = session_logs

            # Если всё ещё слишком большой -- удаляем логи полностью
            payload_size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            if payload_size > 900_000:
                payload["session_logs"] = []
                log_warning("Fsm_4_4_1: Логи удалены из payload (превышен лимит размера)")

            log_info(f"Fsm_4_4_1: Payload после truncation: {payload_size / 1024:.0f} KB")

        # Отправляем
        url = f"{API_BASE_URL}?action=feedback"
        t3 = _time.time()
        # Раздельные таймауты: connect=10s, read=API_TIMEOUT
        timeout_tuple = (10, API_TIMEOUT)
        log_info(f"Fsm_4_4_1: POST -> {url} (timeout=connect:{timeout_tuple[0]}s, "
                 f"read:{timeout_tuple[1]}s, payload:{payload_size / 1024:.0f} KB)")

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=timeout_tuple
            )
        except requests.exceptions.ConnectTimeout:
            t4 = _time.time()
            log_error(f"Fsm_4_4_1: ConnectTimeout за {t4 - t3:.2f}s")
            return False, f"Таймаут подключения к серверу ({timeout_tuple[0]}s)"
        except requests.exceptions.ReadTimeout:
            t4 = _time.time()
            log_error(f"Fsm_4_4_1: ReadTimeout за {t4 - t3:.2f}s")
            return False, f"Таймаут ответа сервера ({timeout_tuple[1]}s)"
        except requests.exceptions.ConnectionError as e:
            t4 = _time.time()
            log_error(f"Fsm_4_4_1: ConnectionError за {t4 - t3:.2f}s: {e}")
            return False, f"Ошибка подключения: {e}"
        except Exception as e:
            t4 = _time.time()
            log_error(f"Fsm_4_4_1: requests.post исключение за {t4 - t3:.2f}s: "
                      f"{type(e).__name__}: {e}")
            return False, f"Ошибка запроса: {type(e).__name__}: {e}"

        t4 = _time.time()
        log_info(f"Fsm_4_4_1: Ответ HTTP {response.status_code} за {t4 - t3:.2f}s "
                 f"(общее время: {t4 - t0:.2f}s), "
                 f"response size: {len(response.content)} bytes")

        if response.status_code == 200:
            data = response.json()
            log_info(f"Fsm_4_4_1: Ответ JSON: status={data.get('status')}, "
                     f"keys={list(data.keys())}")
            if data.get("status") == "success":
                feedback_id = data.get("feedback_id", "")
                log_info(f"Fsm_4_4_1: Успешно! feedback_id={feedback_id}")
                return True, f"ID: {feedback_id}"
            else:
                msg = data.get("message", "Неизвестная ошибка сервера")
                log_error(f"Fsm_4_4_1: Сервер вернул ошибку: {msg}")
                return False, msg
        else:
            body_preview = response.text[:200]
            log_error(f"Fsm_4_4_1: HTTP {response.status_code}: {body_preview}")
            return False, f"HTTP {response.status_code}: {body_preview}"

    def _collect_system_info(self) -> Dict[str, str]:
        """Собрать информацию о системе."""
        try:
            qgis_version = Qgis.QGIS_VERSION
        except Exception:
            qgis_version = "unknown"

        os_type = "unknown"
        system = platform.system().lower()
        if system == "windows":
            os_type = "win"
        elif system == "linux":
            os_type = "linux"
        elif system == "darwin":
            os_type = "mac"

        return {
            "v": PLUGIN_VERSION,
            "qgis": qgis_version,
            "os": os_type,
            "py": f"{sys.version_info.major}.{sys.version_info.minor}"
        }
