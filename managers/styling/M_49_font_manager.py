# -*- coding: utf-8 -*-
"""
M_49: FontManager — тонкий stateful-менеджер шрифтов (регистрация TTF + фабрика QFont).

Канон (роли, семейства, файлы, DXF-стиль, парсер начертаний, «что и как
называется и почему») живёт в QGIS-free модуле `_font_canon.py` — см. его
docstring. M_49 добавляет ТОЛЬКО то, что требует QFontDatabase/QFont:

- `ensure_registered(role | family)` — регистрация TTF из data/fonts/
  (ЕДИНСТВЕННАЯ точка QFontDatabase.addApplicationFont в плагине — C2)
- `make_qfont(family, size_pt, style, letter_spacing_pt)` — фабрика QFont

Дисциплина доступа (R1):
- Данные и чистые функции — ВСЕГДА напрямую из `_font_canon`
  (`parse_font_style`, `get_family`, `dxf_label_text_style`, ...).
  M_49 их НЕ ре-экспортирует — один путь импорта.
- Stateful (`ensure_registered` / `make_qfont`) — через `registry.get('M_49')`.

Потокобезопасность (C2): оба метода вызывать ТОЛЬКО из GUI-потока
(QFontDatabase не thread-safe). Lock/marshalling здесь НЕ писать — при
будущем переносе DXF/лайаут в QgsTask выбрать механизм по месту
(marshalling на GUI-поток ИЛИ пред-регистрация канона на старте плагина);
единая точка регистрации позволяет это без правки потребителей.

Используется: Msm_34_1 (лайауты — этап 2 плана M_49), далее группы по
этапам 3-4 плана `documentation/plans/2026-06-04-M_49-font-manager-centralization.md`.
"""

import os
from typing import Optional, Set, Union

from qgis.PyQt.QtGui import QFont, QFontDatabase

from Daman_QGIS.utils import log_info, log_warning
from . import _font_canon

__all__ = ['FontManager']

# Корень плагина: managers/styling/M_49_font_manager.py -> 3 уровня вверх
_PLUGIN_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_FONTS_DIR = os.path.join(_PLUGIN_ROOT, 'data', 'fonts')


class FontManager:
    """Stateful-менеджер шрифтов: регистрация TTF и фабрика QFont.

    Данные берёт из `_font_canon` (единственный источник правды).
    Регистрируется в registry как 'M_49' (авто, _domain_loader по
    keyword 'Manager' в имени класса).
    """

    # Кэш зарегистрированных СЕМЕЙСТВ (class-level: един при любом доступе —
    # registry-синглтон или прямой инстанс; перенос из Msm_34_1._registered_fonts)
    _registered_fonts: Set[str] = set()

    def __init__(self, iface=None) -> None:
        """Инициализация менеджера.

        C1: полностью независим от iface — НЕ сохраняется, НЕ разыменовывается
        (registry может передать iface=None на раннем старте; шрифтам iface
        не нужен). Совместим с factory-вызовом `(iface)` и `()`.

        Args:
            iface: Интерфейс QGIS (игнорируется)
        """
        # iface намеренно не используется (C1)

    def ensure_registered(
        self,
        role_or_family: Union[_font_canon.FontRole, str],
    ) -> bool:
        """Регистрация TTF-файлов роли из data/fonts/ плагина (если нужно).

        ЕДИНСТВЕННАЯ точка `QFontDatabase.addApplicationFont` в плагине (C2).
        Вызывать ТОЛЬКО из GUI-потока; lock/marshalling НЕ писать — при
        будущем QgsTask выбрать механизм по месту (см. docstring модуля).

        Фикс Д1: результат регистрации проверяется через
        `QFontDatabase.applicationFontFamilies(font_id)` — ТОЧНОЕ имя
        семейства, НЕ substring имени файла (прежний substring-матч
        'gost2.304' не находил файлы gost_2.304*.ttf).

        Args:
            role_or_family: Роль FontRole ИЛИ имя семейства из канона.
                Не-канонное семейство (например, системный шрифт диалога) —
                не задача M_49: регистрация пропускается, возврат False.

        Returns:
            True если семейство доступно (уже было или зарегистрировано)
        """
        # Резолв роли и семейства
        if isinstance(role_or_family, _font_canon.FontRole):
            role: Optional[_font_canon.FontRole] = role_or_family
            family = _font_canon.FAMILIES[role_or_family]
        else:
            family = str(role_or_family)
            role = None
            for canon_role, canon_family in _font_canon.FAMILIES.items():
                if canon_family == family:
                    role = canon_role
                    break
            if role is None:
                # Вне канона — регистрацию не выполняем
                return False

        # Уже зарегистрирован (кэш) или доступен в системе
        if family in FontManager._registered_fonts:
            return True

        db = QFontDatabase()
        if family in db.families():
            FontManager._registered_fonts.add(family)
            return True

        font_files = _font_canon.FONT_FILES.get(role, [])
        if not font_files:
            # DOCUMENT: системный шрифт, файлов в data/fonts нет намеренно
            log_warning(
                f"M_49: семейство '{family}' не найдено в системе "
                f"(роль '{role.value}' без файлов — системный шрифт)"
            )
            return False

        if not os.path.isdir(_FONTS_DIR):
            log_warning(f"M_49: папка шрифтов не найдена: {_FONTS_DIR}")
            return False

        registered_families: Set[str] = set()
        for filename in font_files:
            font_path = os.path.join(_FONTS_DIR, filename)
            if not os.path.isfile(font_path):
                log_warning(f"M_49: файл шрифта не найден: {font_path}")
                continue
            try:
                font_id = QFontDatabase.addApplicationFont(font_path)
            except Exception as e:
                log_warning(f"M_49: ошибка регистрации '{filename}': {e}")
                continue
            if font_id < 0:
                log_warning(f"M_49: не удалось зарегистрировать: {filename}")
                continue
            registered_families.update(
                QFontDatabase.applicationFontFamilies(font_id)
            )

        # Фикс Д1: точное имя семейства, не substring имени файла
        if family in registered_families:
            FontManager._registered_fonts.add(family)
            log_info(
                f"M_49: шрифт '{family}' зарегистрирован "
                f"({len(font_files)} файлов)"
            )
            return True

        log_warning(
            f"M_49: регистрация файлов роли '{role.value}' не дала семейства "
            f"'{family}' (получены: {sorted(registered_families) or 'нет'})"
        )
        return False

    def make_qfont(
        self,
        family: str,
        size_pt: float,
        style: str = "",
        letter_spacing_pt: float = 0.0,
    ) -> QFont:
        """Фабрика QFont: регистрация + начертание из БД + letter-spacing.

        Вызывать ТОЛЬКО из GUI-потока (см. ensure_registered / C2).

        НЕ применять к подписям канвы (группа 1) — H1: подписи рассчитывают
        на СИСТЕМНУЮ установку шрифта через F_4_1 и строят QFont(family) без
        application-регистрации; регистрация меняет резолюцию family
        (при коллизии системного и application-шрифта одного семейства Qt
        выбирает недетерминированно). Применять к лайаутам (группа 2).

        Args:
            family: Имя семейства (канонные регистрируются автоматически,
                не-канонные — регистрация пропускается)
            size_pt: Размер в пунктах (<= 0 — размер Qt по умолчанию)
            style: Начертание в любом формате БД ('Bold Italic',
                'bold;italic', 'regular ', '', None-safe через _font_canon)
            letter_spacing_pt: Межбуквенный интервал в пунктах (0.0 = no-op)

        Returns:
            Настроенный QFont
        """
        self.ensure_registered(family)

        font = QFont(family)
        if size_pt > 0:
            font.setPointSizeF(float(size_pt))

        bold, italic = _font_canon.parse_font_style(style)
        font.setBold(bold)
        font.setItalic(italic)

        # C3: letter-spacing ТОЛЬКО делегированием в Msm_46_5 — НЕ
        # переизобретать (PercentageSpacing ломает legend renderer,
        # допустим только AbsoluteSpacing). Lazy-импорт: субмодули
        # подгружаются после инициализации домена.
        from .submodules.Msm_46_5_utils import apply_letter_spacing_to_font
        apply_letter_spacing_to_font(font, letter_spacing_pt)

        return font
