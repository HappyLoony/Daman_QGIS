# -*- coding: utf-8 -*-
"""
Диалог предпросмотра основной карты с выбором варианта отображения
Позволяет выбрать оптимальный масштаб и DPI для основной карты перед экспортом
"""

import sip
import time
from typing import Optional, Tuple, List
from qgis.PyQt.QtCore import Qt, QSize, QRectF, QCoreApplication, QTimer, QEventLoop
from qgis.PyQt.QtGui import QPixmap, QImage, QColor, QPainter
from qgis.PyQt.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QRadioButton, QButtonGroup,
    QGroupBox, QFrame, QSizePolicy, QApplication,
    QProgressBar, QScrollArea, QWidget
)
from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutItemMap,
    QgsLayoutExporter, QgsLayoutRenderContext,
    QgsMapSettings, QgsMapRendererCustomPainterJob,
    QgsMapRendererCache, QgsNetworkAccessManager
)
from Daman_QGIS.utils import log_info, log_warning, log_error
from Daman_QGIS.constants import EXPORT_DPI_ROSREESTR
from Daman_QGIS.core.base_responsive_dialog import BaseResponsiveDialog


class MainPreviewDialog(BaseResponsiveDialog):
    """Диалог предпросмотра основной карты с вариантами отображения

    Показывает 16 вариантов масштаба основной карты в сетке 4x4.
    Базовый масштаб вычисляется из метаданных проекта (масштаб проекта * 100).
    Варианты - коэффициенты от базового масштаба: x0.5...x200 для разных размеров территорий.
    Все варианты с DPI 300 для точного соответствия финальному экспорту
    (согласно Приказу Росреестра от 19.04.2022 N П/0148).

    Для корректной загрузки WMS/WMTS тайлов (НСПД) используются задержки между
    рендерами и waitForFinishedWithEventLoop() для сохранения отзывчивости UI.

    Пользователь выбирает вариант, который применяется к финальному экспорту.
    """

    WIDTH_RATIO = 0.65
    HEIGHT_RATIO = 0.80
    MIN_WIDTH = 700
    MAX_WIDTH = 1200
    MIN_HEIGHT = 500
    MAX_HEIGHT = 900

    # Фиксированный размер превью (как в шаблоне A4)
    PREVIEW_WIDTH_MM = 66.5
    PREVIEW_HEIGHT_MM = 49.5

    # Варианты отображения: (dpi, scale_factor)
    # scale_factor - множитель относительно базового масштаба main_map
    # (после adaptive-сдвига экстента с учётом legend + overview).
    # Диапазон от x0.5 (крупнее, территория занимает больше места)
    # до x500 (мельче, для очень больших территорий).
    SCALE_FACTORS = [
        0.5, 0.75, 1.0, 1.25,
        1.5, 2.0, 3.0, 5.0,
        10.0, 15.0, 25.0, 50.0,
        100.0, 150.0, 200.0, 500.0
    ]
    # 300 DPI - требование Приказа Росреестра от 19.04.2022 N П/0148
    DPI = EXPORT_DPI_ROSREESTR

    DEFAULT_VARIANT_IDX = 2  # x1.0 (базовый масштаб после adaptive)

    def __init__(self, layout: QgsPrintLayout, current_scale: float, parent=None):
        """Инициализация диалога

        Args:
            layout: Макет QGIS с main_map
            current_scale: Текущий масштаб основной карты
            parent: Родительский виджет
        """
        super().__init__(parent)
        self.layout = layout
        self.current_scale = current_scale
        self.selected_variant = 0  # Индекс выбранного варианта (по умолчанию первый)
        self._previews_rendered = False  # Флаг для отложенного рендеринга
        # Cancel-flag: при accept()/reject() цикл рендеринга прерывается на
        # следующей итерации. Без этого флага цикл по 16 SCALE_FACTORS
        # продолжается ~80с после клика OK (бесполезный рендер невидимых
        # превью), блокируя возврат dialog.exec() в F_5_4 / F_1_4.
        self._cancelled: bool = False

        # Кэш для переиспользования отрендеренных слоёв между вариантами масштаба
        # Особенно важно для WMS/WMTS слоёв - позволяет избежать повторной загрузки тайлов
        self._renderer_cache = QgsMapRendererCache()

        # Инициализация сетевого кэша QGIS для WMS/WMTS тайлов
        self._setup_network_cache()

        self.setWindowTitle("Выбор масштаба основной карты")

        self._init_ui()
        # Рендеринг запускается отложенно после показа диалога (см. showEvent)

    def _setup_network_cache(self):
        """Настройка сетевого кэша QGIS для WMS/WMTS запросов

        Инициализирует кэш на основе пользовательских настроек QGIS.
        Кэш хранит HTTP-ответы (тайлы), ускоряя повторные запросы.
        """
        try:
            # Настраиваем NAM с кэшем на основе настроек пользователя
            nam = QgsNetworkAccessManager.instance()
            nam.setupDefaultProxyAndCache()

            # Проверяем состояние кэша
            cache = nam.cache()
            if cache:
                cache_size_mb = cache.cacheSize() / (1024 * 1024)
                max_size_mb = cache.maximumCacheSize() / (1024 * 1024)
                log_info(f"Fsm_1_4_11: Сетевой кэш QGIS: {cache_size_mb:.1f} / {max_size_mb:.1f} MB")
            else:
                log_warning("Fsm_1_4_11: Сетевой кэш QGIS не настроен")
        except Exception as e:
            log_warning(f"Fsm_1_4_11: Ошибка настройки сетевого кэша: {e}")

    def _init_ui(self):
        """Инициализация интерфейса"""
        main_layout = QVBoxLayout()

        # Заголовок
        title_label = QLabel("Выберите масштаб основной карты:")
        title_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        main_layout.addWidget(title_label)

        # Описание
        desc_label = QLabel(
            "Масштаб влияет на охват территории и читаемость подписей на растровой подложке ЦОС."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666; margin-bottom: 5px;")
        main_layout.addWidget(desc_label)

        # Прогресс-бар загрузки тайлов
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(len(self.SCALE_FACTORS))
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Загрузка тайлов: %v / %m")
        main_layout.addWidget(self.progress_bar)

        # Статус загрузки
        self.status_label = QLabel("Подготовка к загрузке...")
        self.status_label.setStyleSheet("color: #888; font-size: 9pt; margin-bottom: 5px;")
        main_layout.addWidget(self.status_label)

        # Группа с вариантами (сетка 2x3)
        variants_group = QGroupBox("Варианты масштаба")
        variants_grid = QGridLayout()

        # Группа радиокнопок
        self.radio_group = QButtonGroup(self)
        self.preview_labels: List[QLabel] = []

        for idx, scale_factor in enumerate(self.SCALE_FACTORS):
            # Позиция в сетке: 4 ряда по 4 колонки
            row = idx // 4
            col = idx % 4

            # Контейнер для варианта
            variant_frame = QFrame()
            variant_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
            variant_layout = QVBoxLayout(variant_frame)

            # Вычисляем реальный масштаб для названия
            # Округляем до тысяч для читаемости, но без агрессивного округления к "красивым" числам
            actual_scale = self.current_scale * scale_factor
            rounded_scale = int(round(actual_scale / 1000) * 1000)
            scale_name = f"1:{rounded_scale:,}".replace(",", " ")

            # Радиокнопка с динамическим названием
            radio = QRadioButton(scale_name)
            radio.setChecked(idx == self.DEFAULT_VARIANT_IDX)
            self.radio_group.addButton(radio, idx)
            variant_layout.addWidget(radio)

            # Метка с превью (placeholder)
            preview_label = QLabel()
            preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview_label.setMinimumSize(180, 135)
            preview_label.setMaximumSize(200, 150)
            preview_label.setStyleSheet(
                "QLabel { background-color: #f0f0f0; border: 1px solid #ccc; }"
            )
            preview_label.setText("Загрузка...")
            self.preview_labels.append(preview_label)
            variant_layout.addWidget(preview_label)

            # Информация о коэффициенте
            factor_label = QLabel(f"x{scale_factor}")
            factor_label.setStyleSheet("color: #888; font-size: 9pt;")
            factor_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            variant_layout.addWidget(factor_label)

            variants_grid.addWidget(variant_frame, row, col)

        variants_group.setLayout(variants_grid)

        # Скролл для сетки вариантов (маленькие экраны)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(variants_group)
        scroll.setMinimumHeight(300)
        main_layout.addWidget(scroll)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.btn_ok = QPushButton("Применить и экспортировать")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        buttons_layout.addWidget(self.btn_ok)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        buttons_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(buttons_layout)
        self.setLayout(main_layout)

    def showEvent(self, event):
        """Обработка события показа диалога

        Запускает рендеринг превью после того как диалог отобразился,
        чтобы пользователь видел прогресс загрузки тайлов.
        """
        super().showEvent(event)

        # Запускаем рендеринг только один раз после первого показа
        if not self._previews_rendered:
            self._previews_rendered = True
            # Небольшая задержка чтобы UI успел отрисоваться
            QTimer.singleShot(100, self._render_previews)

    # Задержка между рендерами - минимум для UI
    RENDER_DELAY_SEC = 0.02
    # Задержка после refresh() - кэш заполнен
    TILE_LOAD_DELAY_SEC = 0.02

    def _render_previews(self):
        """Рендеринг превью для всех вариантов с задержкой между запросами

        Добавляет паузу между рендерингом каждого варианта, чтобы не перегружать
        WMS/WMTS серверы (например НСПД) большим количеством одновременных запросов.

        Использует DPI 300 для соответствия требованиям Росреестра (Приказ П/0148).
        Отображает прогресс загрузки тайлов в прогресс-баре.
        """
        # Находим main_map в макете
        main_map = self._get_main_map()
        if not main_map:
            log_warning("Fsm_1_4_11: main_map не найден в макете")
            self.status_label.setText("Ошибка: карта не найдена")
            self.progress_bar.setVisible(False)
            for label in self.preview_labels:
                label.setText("Карта не найдена")
            return

        # Сохраняем оригинальный масштаб
        original_scale = main_map.scale()

        # DPI 300 - требование Приказа Росреестра П/0148 (экспорт)
        preview_dpi = self.DPI

        log_info(f"Fsm_1_4_11: Начало рендеринга {len(self.SCALE_FACTORS)} превью с DPI={preview_dpi}")

        # НЕ очищаем кэш - переиспользуем загруженные тайлы между вариантами масштаба
        # QgsMapRendererCache хранит отрендеренные слои, включая WMS/WMTS тайлы
        # Это критично для скорости - один и тот же тайл может использоваться в нескольких масштабах

        total_variants = len(self.SCALE_FACTORS)

        # Флаг первого рендера - для него нужна большая задержка на загрузку тайлов
        is_first_render = True

        # Предзагрузка тайлов: устанавливаем средний масштаб и ждём загрузки
        # Это заполнит сетевой кэш QGIS тайлами, которые переиспользуются в других масштабах
        self.status_label.setText("Предзагрузка тайлов подложки...")
        QApplication.processEvents()
        mid_scale = self.current_scale * self.SCALE_FACTORS[len(self.SCALE_FACTORS) // 2]
        main_map.setScale(mid_scale)
        main_map.refresh()
        self._wait_for_tiles_with_events(0.5)  # Ждём загрузки тайлов в сетевой кэш

        # Проверяем что объект не удалён после ожидания
        if sip.isdeleted(main_map):
            log_warning("Fsm_1_4_11: main_map удалён во время предзагрузки тайлов")
            self.status_label.setText("Ошибка: макет был удалён")
            self.progress_bar.setVisible(False)
            return

        # Рендерим каждый вариант с задержкой
        for idx, scale_factor in enumerate(self.SCALE_FACTORS):
            # Cancel-flag: пользователь нажал OK или Cancel — прекращаем рендер
            # оставшихся вариантов. Решает проблему UI-зависания на ~80с.
            if self._cancelled:
                log_info(
                    f"Fsm_1_4_11: Рендер прерван пользователем на варианте "
                    f"{idx}/{len(self.SCALE_FACTORS)}"
                )
                break

            # Проверяем что C++ объект main_map ещё существует
            # QEventLoop может обработать события, удаляющие макет
            if sip.isdeleted(main_map):
                log_warning("Fsm_1_4_11: main_map удалён во время рендеринга, прерываем")
                break

            try:
                # Вычисляем масштаб для отображения в статусе
                actual_scale = int(round(self.current_scale * scale_factor / 1000) * 1000)
                scale_str = f"1:{actual_scale:,}".replace(",", " ")

                # Обновляем прогресс-бар
                self.progress_bar.setValue(idx)
                self.status_label.setText(f"Загрузка тайлов для {scale_str} (x{scale_factor})...")
                QApplication.processEvents()

                # Обновляем UI чтобы показать прогресс в ячейке
                self.preview_labels[idx].setText(f"Загрузка...")
                QApplication.processEvents()

                # Устанавливаем масштаб для варианта
                new_scale = self.current_scale * scale_factor
                main_map.setScale(new_scale)
                main_map.refresh()

                # Даём время на загрузку тайлов WMS/WMTS
                # Первый рендер требует больше времени, последующие используют кэш
                if is_first_render:
                    self._wait_for_tiles_with_events(0.2)
                    is_first_render = False
                else:
                    self._wait_for_tiles_with_events(self.TILE_LOAD_DELAY_SEC)

                # Обновляем статус - рендеринг
                self.status_label.setText(f"Рендеринг {scale_str}...")
                QApplication.processEvents()

                # Рендерим превью с полным DPI
                pixmap = self._render_map_preview(main_map, preview_dpi)

                if pixmap:
                    self.preview_labels[idx].setPixmap(pixmap)
                    self.preview_labels[idx].setText("")
                else:
                    self.preview_labels[idx].setText("Ошибка")

                # Минимальная пауза между рендерами - кэш уже заполнен
                self._wait_for_tiles_with_events(self.RENDER_DELAY_SEC)

            except RuntimeError as e:
                # C++ объект удалён во время QEventLoop
                if "deleted" in str(e).lower():
                    log_warning(f"Fsm_1_4_11: main_map удалён во время рендеринга варианта {idx}")
                    break
                log_error(f"Fsm_1_4_11: Ошибка рендеринга варианта {idx}: {e}")
                self.preview_labels[idx].setText("Ошибка")
            except Exception as e:
                log_error(f"Fsm_1_4_11: Ошибка рендеринга варианта {idx}: {e}")
                self.preview_labels[idx].setText("Ошибка")

        # Восстанавливаем оригинальный масштаб (если объект ещё существует)
        if not sip.isdeleted(main_map):
            main_map.setScale(original_scale)
            main_map.refresh()

        # Завершаем прогресс
        self.progress_bar.setValue(total_variants)
        self.status_label.setText("Загрузка завершена. Выберите масштаб.")
        self.status_label.setStyleSheet("color: #2e7d32; font-size: 9pt; margin-bottom: 5px;")

        # Логируем состояние кэша после рендеринга
        try:
            nam = QgsNetworkAccessManager.instance()
            cache = nam.cache()
            if cache:
                cache_size_mb = cache.cacheSize() / (1024 * 1024)
                log_info(f"Fsm_1_4_11: Превью отрендерены. Сетевой кэш: {cache_size_mb:.1f} MB")
            else:
                log_info("Fsm_1_4_11: Превью вариантов отрендерены")
        except Exception:
            log_info("Fsm_1_4_11: Превью вариантов отрендерены")

    def _wait_for_tiles_with_events(self, seconds: float):
        """Ожидание с обработкой событий UI

        Позволяет загружать WMS/WMTS тайлы в фоне, сохраняя отзывчивость интерфейса.

        Args:
            seconds: Время ожидания в секундах
        """
        # Используем QTimer с QEventLoop для неблокирующего ожидания
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    def _get_main_map(self) -> Optional[QgsLayoutItemMap]:
        """Получение элемента main_map из макета

        Returns:
            QgsLayoutItemMap или None
        """
        for item in self.layout.items():
            if isinstance(item, QgsLayoutItemMap) and item.id() == 'main_map':
                return item
        return None

    def _round_scale(self, scale: float) -> int:
        """Округление масштаба до красивого числа

        Округляет масштаб до ближайшего стандартного значения:
        99999 -> 100000, 49999 -> 50000, 24999 -> 25000 и т.д.

        Args:
            scale: Исходный масштаб

        Returns:
            int: Округлённый масштаб
        """
        if scale <= 0:
            return int(scale)

        # Определяем порядок числа
        import math
        magnitude = 10 ** int(math.log10(scale))

        # Стандартные множители для масштабов
        standard_multipliers = [1, 2, 2.5, 5, 10]

        # Находим ближайший стандартный масштаб
        normalized = scale / magnitude
        best_multiplier = standard_multipliers[0]
        min_diff = abs(normalized - best_multiplier)

        for mult in standard_multipliers:
            diff = abs(normalized - mult)
            if diff < min_diff:
                min_diff = diff
                best_multiplier = mult

        rounded = int(best_multiplier * magnitude)
        return rounded

    def _render_map_preview(self, map_item: QgsLayoutItemMap, dpi: int) -> Optional[QPixmap]:
        """Рендеринг превью только содержимого карты (без остального макета)

        Использует waitForFinishedWithEventLoop() для ожидания завершения рендеринга
        с сохранением отзывчивости UI и возможности загрузки WMS/WMTS тайлов.

        Args:
            map_item: Элемент карты для рендеринга
            dpi: DPI для рендеринга

        Returns:
            QPixmap с превью или None при ошибке
        """
        try:
            # Проверяем что C++ объект ещё существует
            if sip.isdeleted(map_item):
                log_warning("Fsm_1_4_11: map_item удалён, пропускаем рендеринг")
                return None

            # Размер карты в макете (мм)
            map_width_mm = map_item.sizeWithUnits().width()
            map_height_mm = map_item.sizeWithUnits().height()

            # Размер превью в пикселях с учётом DPI
            preview_width_px = int(map_width_mm * dpi / 25.4)
            preview_height_px = int(map_height_mm * dpi / 25.4)

            # Ограничиваем размер для отображения в диалоге
            max_display_width = 200
            max_display_height = 150

            # Настраиваем QgsMapSettings для рендеринга
            map_settings = QgsMapSettings()
            map_settings.setOutputSize(QSize(preview_width_px, preview_height_px))
            map_settings.setOutputDpi(dpi)
            map_settings.setExtent(map_item.extent())
            map_settings.setDestinationCrs(map_item.crs())
            map_settings.setBackgroundColor(QColor(255, 255, 255))

            # Получаем слои из темы карты или из видимых слоев
            # Тема F_1_4_2_main_map содержит только ЦОС + слои 1_1_1 (без ортофото)
            if map_item.followVisibilityPreset() and map_item.followVisibilityPresetName():
                theme_name = map_item.followVisibilityPresetName()
                theme_collection = QgsProject.instance().mapThemeCollection()
                if theme_collection.hasMapTheme(theme_name):
                    layers = theme_collection.mapThemeVisibleLayers(theme_name)
                    map_settings.setLayers(layers)
                else:
                    map_settings.setLayers(map_item.layers())
            else:
                map_settings.setLayers(map_item.layers())

            # Создаем изображение и рендерим
            image = QImage(QSize(preview_width_px, preview_height_px), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor(255, 255, 255))

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            job = QgsMapRendererCustomPainterJob(map_settings, painter)
            # Используем кэш для переиспользования отрендеренных слоёв между вариантами
            # Особенно важно для WMS/WMTS - позволяет избежать повторных сетевых запросов
            job.setCache(self._renderer_cache)
            job.start()
            # Используем waitForFinishedWithEventLoop() для сохранения отзывчивости UI
            # и возможности загрузки WMS/WMTS тайлов в фоне
            job.waitForFinishedWithEventLoop()

            painter.end()

            if image.isNull():
                log_warning("Fsm_1_4_11: Рендеринг вернул пустое изображение")
                return None

            # Масштабируем для отображения в диалоге
            pixmap = QPixmap.fromImage(image)
            scaled_pixmap = pixmap.scaled(
                max_display_width,
                max_display_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            return scaled_pixmap

        except Exception as e:
            log_error(f"Fsm_1_4_11: Ошибка рендеринга превью: {e}")
            return None

    def get_selected_variant(self) -> Tuple[int, float]:
        """Получение выбранного варианта

        Returns:
            Tuple[int, float]: (dpi, scale_factor)
        """
        selected_idx = self.radio_group.checkedId()
        if selected_idx >= 0 and selected_idx < len(self.SCALE_FACTORS):
            return self.DPI, self.SCALE_FACTORS[selected_idx]

        # Fallback на базовый масштаб (x1.0)
        return self.DPI, 1.0

    def accept(self):
        """Обработка нажатия OK

        Устанавливает _cancelled=True чтобы прервать цикл _render_previews()
        на следующей итерации (если он ещё активен). Без этого dialog.exec()
        не возвращается до конца цикла рендера (~80 сек).
        """
        dpi, scale_factor = self.get_selected_variant()
        log_info(f"Fsm_1_4_11: Выбран вариант DPI={dpi}, scale_factor={scale_factor}")
        self._cancelled = True
        super().accept()

    def reject(self):
        """Обработка отмены диалога

        Симметрично accept(): прерывает цикл рендера превью.
        """
        self._cancelled = True
        super().reject()
