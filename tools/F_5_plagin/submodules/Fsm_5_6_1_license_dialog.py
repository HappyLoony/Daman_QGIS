# -*- coding: utf-8 -*-
"""
Fsm_5_6_1_LicenseDialog - GUI диалог управления лицензией

Интерфейс для:
- Активации лицензии по API ключу
- Просмотра статуса лицензии
- Деактивации лицензии
- Копирования Hardware ID
"""

from typing import Optional, Any

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QMessageBox, QFrame, QApplication
)
from qgis.PyQt.QtGui import QFont, QClipboard
from qgis.PyQt.QtCore import Qt

from Daman_QGIS.managers import (
    get_license_manager,
    LicenseStatus
)
from Daman_QGIS.utils import log_info, log_error
from Daman_QGIS.constants import API_KEY_FORMAT


class LicenseDialog(QDialog):
    """Диалог управления лицензией"""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.license_manager = get_license_manager()

        self.setWindowTitle("Daman_QGIS - Управление лицензией")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        self.setup_ui()
        self.refresh_status()

    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Заголовок
        title_label = QLabel("Управление лицензией Daman QGIS")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Группа статуса
        status_group = self._create_status_group()
        layout.addWidget(status_group)

        # Группа активации
        self.activation_group = self._create_activation_group()
        layout.addWidget(self.activation_group)

        # Группа Hardware ID
        hwid_group = self._create_hwid_group()
        layout.addWidget(hwid_group)

        # Разделитель
        layout.addStretch()

        # Кнопки
        button_layout = QHBoxLayout()

        self.deactivate_btn = QPushButton("Деактивировать")
        self.deactivate_btn.clicked.connect(self.on_deactivate)
        self.deactivate_btn.setEnabled(False)
        button_layout.addWidget(self.deactivate_btn)

        button_layout.addStretch()

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _create_status_group(self) -> QGroupBox:
        """Создание группы статуса лицензии"""
        group = QGroupBox("Статус лицензии")
        layout = QVBoxLayout(group)

        # Статус
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("Статус:"))
        self.status_label = QLabel("Проверка...")
        self.status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        # Тип подписки
        sub_layout = QHBoxLayout()
        sub_layout.addWidget(QLabel("Подписка:"))
        self.subscription_label = QLabel("-")
        sub_layout.addWidget(self.subscription_label)
        sub_layout.addStretch()
        layout.addLayout(sub_layout)

        # Срок действия
        expiry_layout = QHBoxLayout()
        expiry_layout.addWidget(QLabel("Действует до:"))
        self.expiry_label = QLabel("-")
        expiry_layout.addWidget(self.expiry_label)
        expiry_layout.addStretch()
        layout.addLayout(expiry_layout)

        # Владелец
        owner_layout = QHBoxLayout()
        owner_layout.addWidget(QLabel("Владелец:"))
        self.owner_label = QLabel("-")
        owner_layout.addWidget(self.owner_label)
        owner_layout.addStretch()
        layout.addLayout(owner_layout)

        return group

    def _create_activation_group(self) -> QGroupBox:
        """Создание группы активации"""
        group = QGroupBox("Активация лицензии")
        layout = QVBoxLayout(group)

        # Описание формата
        format_label = QLabel(f"Введите ключ активации в формате: {API_KEY_FORMAT}")
        format_label.setStyleSheet("color: #666;")
        layout.addWidget(format_label)

        # Поле ввода ключа
        key_layout = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("DAMAN-XXXX-XXXX-XXXX")
        # Не ограничиваем maxLength - форматирование само обрежет лишнее
        self.key_input.textChanged.connect(self._format_key_input)
        key_layout.addWidget(self.key_input)

        self.activate_btn = QPushButton("Активировать")
        self.activate_btn.clicked.connect(self.on_activate)
        self.activate_btn.setEnabled(False)
        key_layout.addWidget(self.activate_btn)

        layout.addLayout(key_layout)

        # Сообщение об ошибке/успехе
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        return group

    def _create_hwid_group(self) -> QGroupBox:
        """Создание группы Hardware ID"""
        group = QGroupBox("Идентификатор компьютера")
        layout = QVBoxLayout(group)

        # Описание
        desc_label = QLabel(
            "Hardware ID используется для привязки лицензии к этому компьютеру. "
            "При смене оборудования может потребоваться повторная активация."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(desc_label)

        # Hardware ID
        hwid_layout = QHBoxLayout()
        self.hwid_label = QLabel("Загрузка...")
        self.hwid_label.setStyleSheet(
            "font-family: monospace; background: #f0f0f0; padding: 5px; border-radius: 3px;"
        )
        self.hwid_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hwid_layout.addWidget(self.hwid_label)

        copy_btn = QPushButton("Копировать")
        copy_btn.clicked.connect(self.on_copy_hwid)
        hwid_layout.addWidget(copy_btn)

        layout.addLayout(hwid_layout)

        return group

    def _format_key_input(self, text: str):
        """Валидация ввода ключа (без автоформатирования)"""
        # Убираем пробелы и приводим к верхнему регистру
        clean_text = text.strip().upper()

        if clean_text != text:
            self.key_input.blockSignals(True)
            self.key_input.setText(clean_text)
            self.key_input.setCursorPosition(len(clean_text))
            self.key_input.blockSignals(False)

        # Активируем кнопку если ключ в правильном формате: DAMAN-XXXX-XXXX-XXXX
        is_valid = (
            len(clean_text) == 19 and
            clean_text.startswith("DAMAN-") and
            clean_text.count("-") == 3
        )

        # DEBUG
        log_info(f"Fsm_5_6_1: key='{clean_text}', len={len(clean_text)}, valid={is_valid}, bytes={[ord(c) for c in clean_text]}")

        self.activate_btn.setEnabled(is_valid)

    def refresh_status(self):
        """Обновление отображения статуса"""
        # Инициализация менеджера если нужно
        if not self.license_manager._initialized:
            self.license_manager.initialize()

        # Hardware ID
        hwid = self.license_manager.get_hardware_id()
        if hwid:
            # Показываем только первые 16 символов
            self.hwid_label.setText(f"{hwid[:16]}...")
        else:
            self.hwid_label.setText("Ошибка получения")

        # Статус лицензии
        if not self.license_manager.is_activated():
            self._show_not_activated()
            return

        # Проверяем лицензию
        is_valid = self.license_manager.verify()
        status = self.license_manager.get_status()

        if status == LicenseStatus.VALID:
            self._show_valid_license()
        elif status == LicenseStatus.EXPIRED:
            self._show_expired_license()
        elif status == LicenseStatus.HARDWARE_MISMATCH:
            self._show_hardware_mismatch()
        else:
            self._show_invalid_license(status)

    def _show_not_activated(self):
        """Отображение неактивированной лицензии"""
        self.status_label.setText("Не активирована")
        self.status_label.setStyleSheet("font-weight: bold; color: #666;")
        self.subscription_label.setText("-")
        self.expiry_label.setText("-")
        self.owner_label.setText("-")

        self.activation_group.setEnabled(True)
        self.deactivate_btn.setEnabled(False)

    def _show_valid_license(self):
        """Отображение валидной лицензии"""
        self.status_label.setText("Активна")
        self.status_label.setStyleSheet("font-weight: bold; color: green;")

        license_info = self.license_manager.get_license_info()
        if license_info:
            self.subscription_label.setText(license_info.get("subscription_type", "-"))
            self.owner_label.setText(license_info.get("user_name", "-"))

            expires = license_info.get("expires_at")
            if expires:
                # Форматируем дату
                if expires.endswith("Z"):
                    expires = expires[:-1]
                self.expiry_label.setText(expires[:10])
            else:
                self.expiry_label.setText("Бессрочно")

        self.activation_group.setEnabled(False)
        self.deactivate_btn.setEnabled(True)

    def _show_expired_license(self):
        """Отображение истёкшей лицензии"""
        self.status_label.setText("Истекла")
        self.status_label.setStyleSheet("font-weight: bold; color: orange;")

        expiry = self.license_manager.get_expiry_date()
        if expiry:
            self.expiry_label.setText(f"{expiry[:10]} (истекла)")

        self.activation_group.setEnabled(True)
        self.deactivate_btn.setEnabled(True)
        self.message_label.setText("Срок действия лицензии истёк. Продлите подписку.")
        self.message_label.setStyleSheet("color: orange;")

    def _show_hardware_mismatch(self):
        """Отображение несовпадения Hardware ID"""
        self.status_label.setText("Ошибка привязки")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")

        self.activation_group.setEnabled(True)
        self.deactivate_btn.setEnabled(True)
        self.message_label.setText(
            "Лицензия привязана к другому компьютеру. "
            "Деактивируйте на старом ПК или обратитесь к разработчику."
        )
        self.message_label.setStyleSheet("color: red;")

    def _show_invalid_license(self, status: LicenseStatus):
        """Отображение невалидной лицензии"""
        self.status_label.setText(f"Ошибка: {status.value}")
        self.status_label.setStyleSheet("font-weight: bold; color: red;")

        self.activation_group.setEnabled(True)
        self.deactivate_btn.setEnabled(False)

    def on_activate(self):
        """Обработка активации лицензии"""
        api_key = self.key_input.text().strip()

        if not api_key:
            self.message_label.setText("Введите ключ активации")
            self.message_label.setStyleSheet("color: red;")
            return

        self.activate_btn.setEnabled(False)
        self.activate_btn.setText("Активация...")
        self.message_label.setText("")

        try:
            success, message = self.license_manager.activate(api_key)

            if success:
                self.message_label.setText("Лицензия успешно активирована!")
                self.message_label.setStyleSheet("color: green;")
                self.key_input.clear()
                self.refresh_status()
                log_info("F_5_6: Лицензия активирована")
            else:
                self.message_label.setText(message)
                self.message_label.setStyleSheet("color: red;")
                log_error(f"F_5_6: Ошибка активации: {message}")

        except Exception as e:
            self.message_label.setText(f"Ошибка: {e}")
            self.message_label.setStyleSheet("color: red;")
            log_error(f"F_5_6: Исключение при активации: {e}")

        finally:
            self.activate_btn.setEnabled(True)
            self.activate_btn.setText("Активировать")

    def on_deactivate(self):
        """Обработка деактивации лицензии"""
        reply = QMessageBox.question(
            self,
            "Подтверждение деактивации",
            "Вы уверены, что хотите деактивировать лицензию на этом компьютере?\n\n"
            "После деактивации вы сможете активировать её на другом ПК.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        self.deactivate_btn.setEnabled(False)
        self.deactivate_btn.setText("Деактивация...")

        try:
            success = self.license_manager.deactivate()

            if success:
                QMessageBox.information(
                    self,
                    "Деактивация",
                    "Лицензия успешно деактивирована.\n"
                    "Теперь вы можете активировать её на другом компьютере."
                )
                self.refresh_status()
                log_info("F_5_6: Лицензия деактивирована")
            else:
                QMessageBox.warning(
                    self,
                    "Ошибка",
                    "Не удалось деактивировать лицензию.\n"
                    "Попробуйте позже или обратитесь к разработчику."
                )

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка деактивации: {e}")
            log_error(f"F_5_6: Исключение при деактивации: {e}")

        finally:
            self.deactivate_btn.setEnabled(True)
            self.deactivate_btn.setText("Деактивировать")

    def on_copy_hwid(self):
        """Копирование Hardware ID в буфер обмена"""
        hwid = self.license_manager.get_hardware_id()
        if hwid:
            clipboard = QApplication.clipboard()
            clipboard.setText(hwid)

            # Временное сообщение
            self.hwid_label.setText("Скопировано!")
            from qgis.PyQt.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self.hwid_label.setText(f"{hwid[:16]}..."))

            log_info("F_5_6: Hardware ID скопирован в буфер обмена")
