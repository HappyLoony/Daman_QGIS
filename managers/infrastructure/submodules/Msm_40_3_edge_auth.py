# -*- coding: utf-8 -*-
"""
Msm_40_3_EdgeAuth - Авторизация НСПД через системный Microsoft Edge + CDP

Запускает Edge с --remote-debugging-port, пользователь авторизуется
в реальном браузере через Госуслуги (ЕСИА). После авторизации cookies
извлекаются через Chrome DevTools Protocol (WebSocket).

Используется как основной метод авторизации на Windows.
Qt5 QWebEngine (Chromium 87 в Qt 5.15.13/QGIS 3.40) не может запустить SPA
nspd.gov.ru -- JS-бандл падает с "Uncaught SyntaxError: Unexpected reserved word"
(top-level await / ES2022+, требуется Chromium 89+). Проверено 2026-02-24.

Зависимости: ТОЛЬКО Python stdlib (socket, struct, http.client, subprocess, json)
Платформа: Windows 10/11 (Microsoft Edge предустановлен)
"""

import hashlib
import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from typing import Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QMessageBox
)

from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog
from Daman_QGIS.constants import (
    NSPD_AUTH_URL, NSPD_AUTH_COOKIE_DOMAINS, EDGE_CDP_STARTUP_TIMEOUT
)
from Daman_QGIS.utils import log_info, log_warning, log_error


# =============================================================================
# Edge detection
# =============================================================================

def find_edge_executable() -> Optional[str]:
    """Найти исполняемый файл Microsoft Edge.

    Порядок поиска:
    1. Стандартные пути Program Files (x86 и x64)
    2. Реестр Windows (App Paths)
    3. shutil.which

    Returns:
        Полный путь к msedge.exe или None
    """
    # 1. Прямая проверка стандартных путей
    for env_var in ('ProgramFiles(x86)', 'ProgramFiles'):
        program_files = os.environ.get(env_var, '')
        if program_files:
            path = os.path.join(
                program_files, 'Microsoft', 'Edge', 'Application', 'msedge.exe'
            )
            if os.path.isfile(path):
                return path

    # 2. Реестр Windows
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
        )
        value, _ = winreg.QueryValueEx(key, "")
        winreg.CloseKey(key)
        if value and os.path.isfile(value):
            return value
    except Exception:
        pass

    # 3. shutil.which fallback
    result = shutil.which('msedge')
    return result


def is_edge_available() -> bool:
    """Проверка доступности Microsoft Edge."""
    return find_edge_executable() is not None


# =============================================================================
# Minimal WebSocket client for CDP (RFC 6455)
# =============================================================================

class _CdpWebSocketClient:
    """Минимальный WebSocket клиент для Chrome DevTools Protocol.

    Поддерживает ровно один цикл: connect -> send_json -> receive_json -> close.
    Клиентские фреймы маскированы (обязательно по RFC 6455).
    Обрабатывает ping от сервера (отвечает pong).
    """

    _WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, ws_url: str) -> None:
        """
        Args:
            ws_url: WebSocket URL вида ws://host:port/path
        """
        # Парсинг ws://host:port/path
        cleaned = ws_url.replace("ws://", "")
        host_port, *path_parts = cleaned.split("/", 1)
        self._path = "/" + path_parts[0] if path_parts else "/"

        if ":" in host_port:
            host, port_str = host_port.split(":", 1)
            self._host = host
            self._port = int(port_str)
        else:
            self._host = host_port
            self._port = 80

        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        """Установить WebSocket соединение (TCP + HTTP 101 Upgrade)."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(10)
        self._sock.connect((self._host, self._port))

        # WebSocket handshake
        import base64
        key = base64.b64encode(os.urandom(16)).decode()

        request = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self._sock.sendall(request.encode())

        # Читаем ответ (101 Switching Protocols)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Msm_40_3: Соединение закрыто при handshake")
            response += chunk

        status_line = response.split(b"\r\n")[0]
        if b"101" not in status_line:
            raise ConnectionError(
                f"Msm_40_3: WebSocket handshake failed: {status_line.decode(errors='replace')}"
            )

        # Валидация Sec-WebSocket-Accept
        import base64 as b64
        expected_accept = b64.b64encode(
            hashlib.sha1((key + self._WS_MAGIC).encode()).digest()
        ).decode()
        if expected_accept.encode() not in response:
            log_warning("Msm_40_3: Sec-WebSocket-Accept не совпадает (продолжаем)")

        log_info("Msm_40_3: WebSocket соединение установлено")

    def send_json(self, data: dict) -> None:
        """Отправить JSON как текстовый WebSocket фрейм (masked)."""
        if not self._sock:
            raise ConnectionError("Msm_40_3: WebSocket не подключён")

        payload = json.dumps(data).encode('utf-8')
        frame = self._encode_frame(payload)
        self._sock.sendall(frame)

    def receive_json(self) -> dict:
        """Получить JSON из WebSocket фрейма.

        Автоматически обрабатывает ping (отвечает pong) и пропускает events.
        """
        if not self._sock:
            raise ConnectionError("Msm_40_3: WebSocket не подключён")

        while True:
            opcode, payload = self._read_frame()

            # Ping -> Pong
            if opcode == 0x09:
                self._send_pong(payload)
                continue

            # Close
            if opcode == 0x08:
                raise ConnectionError("Msm_40_3: Сервер закрыл WebSocket")

            # Text frame
            if opcode == 0x01:
                return json.loads(payload.decode('utf-8'))

            # Другие опкоды -- пропускаем
            log_warning(f"Msm_40_3: Неожиданный opcode: {opcode:#x}")

    def close(self) -> None:
        """Закрыть WebSocket соединение."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # --- Private ---

    def _encode_frame(self, payload: bytes) -> bytes:
        """Кодирование текстового фрейма с маскированием (клиент -> сервер)."""
        frame = bytearray()
        frame.append(0x81)  # FIN=1, opcode=text

        mask_key = os.urandom(4)
        length = len(payload)

        if length < 126:
            frame.append(0x80 | length)  # MASK=1
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack('>Q', length))

        frame.extend(mask_key)

        # XOR masking
        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask_key[i % 4]
        frame.extend(masked)

        return bytes(frame)

    def _read_frame(self) -> tuple:
        """Чтение одного WebSocket фрейма (сервер -> клиент, без маски)."""
        header = self._recv_exact(2)
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F

        if length == 126:
            length = struct.unpack('>H', self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack('>Q', self._recv_exact(8))[0]

        mask_key = self._recv_exact(4) if masked else None

        payload = self._recv_exact(length)

        if masked and mask_key:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        return opcode, payload

    def _recv_exact(self, n: int) -> bytes:
        """Чтение ровно n байт из сокета."""
        if not self._sock:
            raise ConnectionError("Msm_40_3: Socket closed")

        data = b""
        while len(data) < n:
            chunk = self._sock.recv(min(n - len(data), 65536))
            if not chunk:
                raise ConnectionError("Msm_40_3: Соединение закрыто при чтении")
            data += chunk
        return data

    def _send_pong(self, payload: bytes) -> None:
        """Отправить pong фрейм в ответ на ping."""
        frame = bytearray()
        frame.append(0x8A)  # FIN=1, opcode=pong

        mask_key = os.urandom(4)
        length = len(payload)

        if length < 126:
            frame.append(0x80 | length)
        else:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', length))

        frame.extend(mask_key)
        masked = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        frame.extend(masked)

        if self._sock:
            self._sock.sendall(bytes(frame))


# =============================================================================
# Edge CDP Session
# =============================================================================

class _EdgeCdpSession:
    """Управление жизненным циклом Edge и CDP-коммуникацией."""

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._temp_dir: Optional[str] = None
        self._port: int = 0

    def start(self, url: str) -> bool:
        """Запустить Edge с CDP на указанный URL.

        Args:
            url: URL для открытия (https://nspd.gov.ru)

        Returns:
            True если Edge запущен успешно
        """
        edge_path = find_edge_executable()
        if not edge_path:
            log_error("Msm_40_3: Microsoft Edge не найден")
            return False

        # Свободный порт
        self._port = self._find_free_port()
        if not self._port:
            log_error("Msm_40_3: Не удалось найти свободный порт")
            return False

        # Временная директория для user-data-dir
        self._temp_dir = tempfile.mkdtemp(prefix='daman_edge_')

        cmd = [
            edge_path,
            f'--remote-debugging-port={self._port}',
            f'--user-data-dir={self._temp_dir}',
            '--no-first-run',
            '--disable-default-apps',
            '--disable-extensions',
            url
        ]

        try:
            self._process = subprocess.Popen(cmd)
            log_info(f"Msm_40_3: Edge запущен (PID={self._process.pid}, "
                     f"CDP port={self._port})")
            return True

        except Exception as e:
            log_error(f"Msm_40_3: Ошибка запуска Edge: {e}")
            self._cleanup_temp_dir()
            return False

    def is_running(self) -> bool:
        """Проверка что Edge-процесс жив."""
        return self._process is not None and self._process.poll() is None

    def extract_cookies(self, domains: List[str]) -> Dict[str, str]:
        """Извлечь cookies через CDP.

        Args:
            domains: Список доменов для фильтрации

        Returns:
            Словарь {name: value} отфильтрованных cookies
        """
        # 1. Получить WebSocket URL через CDP HTTP endpoint
        ws_url = self._get_ws_debugger_url()
        if not ws_url:
            return {}

        # 2. Подключиться по WebSocket и запросить cookies
        client = _CdpWebSocketClient(ws_url)
        try:
            client.connect()
            client.send_json({"id": 1, "method": "Storage.getCookies"})
            response = client.receive_json()
        except Exception as e:
            log_error(f"Msm_40_3: Ошибка CDP WebSocket: {e}")
            return {}
        finally:
            client.close()

        # 3. Фильтрация по доменам
        cookies: Dict[str, str] = {}
        all_cookies = response.get("result", {}).get("cookies", [])
        log_info(f"Msm_40_3: CDP вернул {len(all_cookies)} cookies всего")

        for cookie in all_cookies:
            cookie_domain = cookie.get("domain", "")
            if any(d in cookie_domain for d in domains):
                cookies[cookie["name"]] = cookie["value"]

        log_info(f"Msm_40_3: После фильтрации: {len(cookies)} cookies "
                 f"(домены: {domains})")
        return cookies

    def stop(self) -> None:
        """Остановить Edge и очистить временные файлы."""
        if self._process:
            try:
                self._process.kill()
                self._process.wait(timeout=5)
                log_info(f"Msm_40_3: Edge остановлен (PID={self._process.pid})")
            except Exception as e:
                log_warning(f"Msm_40_3: Ошибка остановки Edge: {e}")
            self._process = None

        self._cleanup_temp_dir()

    # --- Private ---

    @staticmethod
    def _find_free_port() -> int:
        """Найти свободный TCP порт через OS."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                return s.getsockname()[1]
        except Exception as e:
            log_error(f"Msm_40_3: Ошибка поиска порта: {e}")
            return 0

    def _get_ws_debugger_url(self) -> Optional[str]:
        """Получить WebSocket URL для CDP через HTTP endpoint /json/version.

        Ожидает готовности CDP endpoint с таймаутом.
        """
        deadline = time.time() + EDGE_CDP_STARTUP_TIMEOUT
        last_error = ""

        while time.time() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=2)
                conn.request("GET", "/json/version")
                resp = conn.getresponse()
                data = json.loads(resp.read().decode())
                conn.close()

                ws_url = data.get("webSocketDebuggerUrl", "")
                if ws_url:
                    log_info(f"Msm_40_3: CDP endpoint готов: {ws_url[:60]}...")
                    return ws_url

            except Exception as e:
                last_error = str(e)

            time.sleep(0.5)

        log_error(f"Msm_40_3: CDP endpoint не ответил за {EDGE_CDP_STARTUP_TIMEOUT}с "
                  f"(последняя ошибка: {last_error})")
        return None

    def _cleanup_temp_dir(self) -> None:
        """Удалить временную директорию Edge."""
        if self._temp_dir and os.path.isdir(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, onerror=lambda *_: None)
                log_info(f"Msm_40_3: Temp директория удалена: {self._temp_dir}")
            except Exception as e:
                log_warning(f"Msm_40_3: Не удалось удалить {self._temp_dir}: {e}")
            self._temp_dir = None


# =============================================================================
# Edge Auth Dialog
# =============================================================================

class Msm_40_3_EdgeAuthDialog(BaseResponsiveDialog):
    """Диалог авторизации НСПД через системный Edge + CDP.

    Тот же интерфейс что у Msm_40_1_AuthBrowserDialog:
    - exec() -> QDialog.Accepted / QDialog.Rejected
    - get_collected_cookies() -> Dict[str, str]

    Usage:
        dialog = Msm_40_3_EdgeAuthDialog(parent)
        if dialog.exec() == QDialog.Accepted:
            cookies = dialog.get_collected_cookies()
    """

    SIZING_MODE = 'content'
    MAX_WIDTH = 550
    MAX_HEIGHT = 400

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]

        self._cookies: Dict[str, str] = {}
        self._session = _EdgeCdpSession()

        self.setWindowTitle("Авторизация НСПД")
        self.setFixedWidth(500)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint  # type: ignore[operator]
        )

        self._setup_ui()
        self._start_edge()

    def _setup_ui(self) -> None:
        """Создание интерфейса."""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Заголовок
        title = QLabel("Авторизация через Microsoft Edge")
        title.setStyleSheet("font-size: 11pt; font-weight: bold;")
        layout.addWidget(title)

        # Инструкция
        instruction = QLabel(
            "1. В открывшемся окне Edge нажмите 'Войти' на сайте НСПД\n"
            "2. Пройдите авторизацию через Госуслуги (ЕСИА)\n"
            "3. После входа вернитесь сюда и нажмите 'Готово'"
        )
        instruction.setStyleSheet("font-size: 10pt; padding: 4px;")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        # Статус
        self._status_label = QLabel("Запуск Edge...")
        self._status_label.setStyleSheet(
            "color: #666; font-size: 9pt; padding: 4px;"
        )
        layout.addWidget(self._status_label)

        # Кнопки
        btn_layout = QHBoxLayout()

        self._done_btn = QPushButton("Готово")
        self._done_btn.setMinimumWidth(120)
        self._done_btn.setDefault(True)
        self._done_btn.clicked.connect(self._finish)
        btn_layout.addWidget(self._done_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self._cancel)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _start_edge(self) -> None:
        """Запуск Edge с CDP."""
        if self._session.start(NSPD_AUTH_URL):
            self._status_label.setText(
                f"Edge открыт с {NSPD_AUTH_URL}. "
                "Авторизуйтесь и нажмите 'Готово'."
            )
            self._status_label.setStyleSheet(
                "color: green; font-size: 9pt; padding: 4px;"
            )
        else:
            self._status_label.setText(
                "Не удалось запустить Microsoft Edge"
            )
            self._status_label.setStyleSheet(
                "color: red; font-size: 9pt; padding: 4px; font-weight: bold;"
            )
            self._done_btn.setEnabled(False)

    def _finish(self) -> None:
        """Извлечение cookies и завершение."""
        if not self._session.is_running():
            QMessageBox.warning(
                self,
                "Авторизация НСПД",
                "Edge был закрыт.\n\n"
                "Нажмите 'Отмена' и попробуйте снова."
            )
            return

        self._status_label.setText("Извлечение cookies...")
        self._status_label.setStyleSheet(
            "color: #666; font-size: 9pt; padding: 4px;"
        )
        # Обновить UI перед блокирующей операцией
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()

        cookies = self._session.extract_cookies(NSPD_AUTH_COOKIE_DOMAINS)

        if cookies:
            self._cookies = cookies
            log_info(f"Msm_40_3: Авторизация завершена, "
                     f"получено {len(cookies)} cookies")
            self._session.stop()
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "Авторизация НСПД",
                "Cookies не найдены.\n\n"
                "Убедитесь что вы:\n"
                "- Нажали 'Войти' на сайте НСПД\n"
                "- Прошли авторизацию через Госуслуги\n"
                "- Видите личный кабинет на nspd.gov.ru"
            )

    def _cancel(self) -> None:
        """Отмена авторизации."""
        self._session.stop()
        self.reject()

    def closeEvent(self, event: object) -> None:
        """Очистка при закрытии диалога."""
        self._session.stop()
        super().closeEvent(event)  # type: ignore[arg-type]

    def get_collected_cookies(self) -> Dict[str, str]:
        """Получить собранные cookies.

        Returns:
            Словарь {name: value} cookies
        """
        return dict(self._cookies)
