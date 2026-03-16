# -*- coding: utf-8 -*-
"""
Fsm_4_2_T_qt6_compatibility - Тест совместимости с Qt6/QGIS 4.0

Проверяет готовность плагина к миграции на Qt6 (QGIS 4.0).

Проверки (статический анализ):
1.  metadata.txt: supportsQt6, qgisMaximumVersion
2.  Использование qgis.PyQt вместо прямых импортов PyQt5/PyQt6
3.  Qt enum scoping (Qt.AlignCenter -> Qt.AlignmentFlag.AlignCenter)
4.  QWidgets enum scoping (QMessageBox.Yes -> QMessageBox.StandardButton.Yes)
5.  QVariant типы (QVariant.String -> QMetaType.Type.QString)
6.  QVariant() конструктор (QVariant() -> None)
7.  Deprecated методы: exec_(), print_()
8.  Перемещённые классы (QAction -> QtGui)
9.  Удалённые глобальные объекты (qApp)
10. Удалённые модули Qt (QtScript, QtWebKit)
11. QgsWkbTypes -> Qgis.WkbType / Qgis.GeometryType
12. QgsUnitTypes -> Qgis.RenderUnit / Qgis.LayoutUnit

Проверки (runtime):
13. Qt6 fully-qualified enum resolution в текущей среде
14. Наличие методов exec/exec_, QAction в QtGui/QtWidgets
15. QVariant поведение, QMetaType.Type доступность
16. Processing алгоритмы плагина в registry
17. Сторонние библиотеки (ezdxf, xlsxwriter, requests, lxml)

Основано на:
- https://github.com/qgis/QGIS/wiki/Plugin-migration-to-be-compatible-with-Qt5-and-Qt6
- https://www.riverbankcomputing.com/static/Docs/PyQt6/pyqt5_differences.html
"""

import os
import re
from typing import Any, Dict, List, Tuple
from pathlib import Path


class TestQt6Compatibility:
    """Тесты совместимости с Qt6"""

    # ----------------------------------------------------------------
    # Паттерны импортов
    # ----------------------------------------------------------------
    DEPRECATED_IMPORTS = [
        (r'from PyQt5\.', 'from qgis.PyQt.'),
        (r'from PyQt6\.', 'from qgis.PyQt.'),
        (r'import PyQt5', 'from qgis import PyQt'),
        (r'import PyQt6', 'from qgis import PyQt'),
    ]

    # ----------------------------------------------------------------
    # Qt namespace enum scoping (Qt.X -> Qt.EnumClass.X)
    # ----------------------------------------------------------------
    QT_ENUM_PATTERNS: List[Tuple[str, str, str]] = [
        # --- ItemDataRole ---
        (r'(?<!\w)Qt\.UserRole(?!\w)', 'Qt.ItemDataRole.UserRole', 'Qt.UserRole'),
        (r'(?<!\w)Qt\.DisplayRole(?!\w)', 'Qt.ItemDataRole.DisplayRole', 'Qt.DisplayRole'),
        (r'(?<!\w)Qt\.EditRole(?!\w)', 'Qt.ItemDataRole.EditRole', 'Qt.EditRole'),
        (r'(?<!\w)Qt\.CheckStateRole(?!\w)', 'Qt.ItemDataRole.CheckStateRole', 'Qt.CheckStateRole'),
        (r'(?<!\w)Qt\.DecorationRole(?!\w)', 'Qt.ItemDataRole.DecorationRole', 'Qt.DecorationRole'),
        (r'(?<!\w)Qt\.ToolTipRole(?!\w)', 'Qt.ItemDataRole.ToolTipRole', 'Qt.ToolTipRole'),
        (r'(?<!\w)Qt\.BackgroundRole(?!\w)', 'Qt.ItemDataRole.BackgroundRole', 'Qt.BackgroundRole'),
        (r'(?<!\w)Qt\.ForegroundRole(?!\w)', 'Qt.ItemDataRole.ForegroundRole', 'Qt.ForegroundRole'),

        # --- CursorShape ---
        (r'(?<!\w)Qt\.WaitCursor(?!\w)', 'Qt.CursorShape.WaitCursor', 'Qt.WaitCursor'),
        (r'(?<!\w)Qt\.ArrowCursor(?!\w)', 'Qt.CursorShape.ArrowCursor', 'Qt.ArrowCursor'),
        (r'(?<!\w)Qt\.CrossCursor(?!\w)', 'Qt.CursorShape.CrossCursor', 'Qt.CrossCursor'),
        (r'(?<!\w)Qt\.PointingHandCursor(?!\w)', 'Qt.CursorShape.PointingHandCursor', 'Qt.PointingHandCursor'),
        (r'(?<!\w)Qt\.BusyCursor(?!\w)', 'Qt.CursorShape.BusyCursor', 'Qt.BusyCursor'),
        (r'(?<!\w)Qt\.ForbiddenCursor(?!\w)', 'Qt.CursorShape.ForbiddenCursor', 'Qt.ForbiddenCursor'),

        # --- Orientation ---
        (r'(?<!\w)Qt\.Horizontal(?!\w)', 'Qt.Orientation.Horizontal', 'Qt.Horizontal'),
        (r'(?<!\w)Qt\.Vertical(?!\w)', 'Qt.Orientation.Vertical', 'Qt.Vertical'),

        # --- AlignmentFlag ---
        (r'(?<!\w)Qt\.AlignLeft(?!\w)', 'Qt.AlignmentFlag.AlignLeft', 'Qt.AlignLeft'),
        (r'(?<!\w)Qt\.AlignRight(?!\w)', 'Qt.AlignmentFlag.AlignRight', 'Qt.AlignRight'),
        (r'(?<!\w)Qt\.AlignCenter(?!\w)', 'Qt.AlignmentFlag.AlignCenter', 'Qt.AlignCenter'),
        (r'(?<!\w)Qt\.AlignTop(?!\w)', 'Qt.AlignmentFlag.AlignTop', 'Qt.AlignTop'),
        (r'(?<!\w)Qt\.AlignBottom(?!\w)', 'Qt.AlignmentFlag.AlignBottom', 'Qt.AlignBottom'),
        (r'(?<!\w)Qt\.AlignVCenter(?!\w)', 'Qt.AlignmentFlag.AlignVCenter', 'Qt.AlignVCenter'),
        (r'(?<!\w)Qt\.AlignHCenter(?!\w)', 'Qt.AlignmentFlag.AlignHCenter', 'Qt.AlignHCenter'),
        (r'(?<!\w)Qt\.AlignJustify(?!\w)', 'Qt.AlignmentFlag.AlignJustify', 'Qt.AlignJustify'),

        # --- GlobalColor ---
        (r'(?<!\w)Qt\.white(?!\w)', 'Qt.GlobalColor.white', 'Qt.white'),
        (r'(?<!\w)Qt\.black(?!\w)', 'Qt.GlobalColor.black', 'Qt.black'),
        (r'(?<!\w)Qt\.red(?!\w)', 'Qt.GlobalColor.red', 'Qt.red'),
        (r'(?<!\w)Qt\.blue(?!\w)', 'Qt.GlobalColor.blue', 'Qt.blue'),
        (r'(?<!\w)Qt\.green(?!\w)', 'Qt.GlobalColor.green', 'Qt.green'),
        (r'(?<!\w)Qt\.yellow(?!\w)', 'Qt.GlobalColor.yellow', 'Qt.yellow'),
        (r'(?<!\w)Qt\.gray(?!\w)', 'Qt.GlobalColor.gray', 'Qt.gray'),
        (r'(?<!\w)Qt\.darkRed(?!\w)', 'Qt.GlobalColor.darkRed', 'Qt.darkRed'),
        (r'(?<!\w)Qt\.darkBlue(?!\w)', 'Qt.GlobalColor.darkBlue', 'Qt.darkBlue'),
        (r'(?<!\w)Qt\.darkGreen(?!\w)', 'Qt.GlobalColor.darkGreen', 'Qt.darkGreen'),
        (r'(?<!\w)Qt\.transparent(?!\w)', 'Qt.GlobalColor.transparent', 'Qt.transparent'),

        # --- CheckState ---
        (r'(?<!\w)Qt\.Checked(?!\w)', 'Qt.CheckState.Checked', 'Qt.Checked'),
        (r'(?<!\w)Qt\.Unchecked(?!\w)', 'Qt.CheckState.Unchecked', 'Qt.Unchecked'),
        (r'(?<!\w)Qt\.PartiallyChecked(?!\w)', 'Qt.CheckState.PartiallyChecked', 'Qt.PartiallyChecked'),

        # --- AspectRatioMode ---
        (r'(?<!\w)Qt\.KeepAspectRatio(?!\w)', 'Qt.AspectRatioMode.KeepAspectRatio', 'Qt.KeepAspectRatio'),
        (r'(?<!\w)Qt\.IgnoreAspectRatio(?!\w)', 'Qt.AspectRatioMode.IgnoreAspectRatio', 'Qt.IgnoreAspectRatio'),

        # --- TransformationMode ---
        (r'(?<!\w)Qt\.SmoothTransformation(?!\w)', 'Qt.TransformationMode.SmoothTransformation', 'Qt.SmoothTransformation'),
        (r'(?<!\w)Qt\.FastTransformation(?!\w)', 'Qt.TransformationMode.FastTransformation', 'Qt.FastTransformation'),

        # --- PenStyle ---
        (r'(?<!\w)Qt\.SolidLine(?!\w)', 'Qt.PenStyle.SolidLine', 'Qt.SolidLine'),
        (r'(?<!\w)Qt\.DashLine(?!\w)', 'Qt.PenStyle.DashLine', 'Qt.DashLine'),
        (r'(?<!\w)Qt\.DotLine(?!\w)', 'Qt.PenStyle.DotLine', 'Qt.DotLine'),
        (r'(?<!\w)Qt\.DashDotLine(?!\w)', 'Qt.PenStyle.DashDotLine', 'Qt.DashDotLine'),
        (r'(?<!\w)Qt\.DashDotDotLine(?!\w)', 'Qt.PenStyle.DashDotDotLine', 'Qt.DashDotDotLine'),
        (r'(?<!\w)Qt\.NoPen(?!\w)', 'Qt.PenStyle.NoPen', 'Qt.NoPen'),

        # --- BrushStyle ---
        (r'(?<!\w)Qt\.SolidPattern(?!\w)', 'Qt.BrushStyle.SolidPattern', 'Qt.SolidPattern'),
        (r'(?<!\w)Qt\.NoBrush(?!\w)', 'Qt.BrushStyle.NoBrush', 'Qt.NoBrush'),
        (r'(?<!\w)Qt\.Dense1Pattern(?!\w)', 'Qt.BrushStyle.Dense1Pattern', 'Qt.Dense1Pattern'),

        # --- ItemFlag ---
        (r'(?<!\w)Qt\.ItemIsEnabled(?!\w)', 'Qt.ItemFlag.ItemIsEnabled', 'Qt.ItemIsEnabled'),
        (r'(?<!\w)Qt\.ItemIsSelectable(?!\w)', 'Qt.ItemFlag.ItemIsSelectable', 'Qt.ItemIsSelectable'),
        (r'(?<!\w)Qt\.ItemIsEditable(?!\w)', 'Qt.ItemFlag.ItemIsEditable', 'Qt.ItemIsEditable'),
        (r'(?<!\w)Qt\.ItemIsUserCheckable(?!\w)', 'Qt.ItemFlag.ItemIsUserCheckable', 'Qt.ItemIsUserCheckable'),
        (r'(?<!\w)Qt\.ItemIsTristate(?!\w)', 'Qt.ItemFlag.ItemIsAutoTristate', 'Qt.ItemIsTristate (renamed)'),
        (r'(?<!\w)Qt\.ItemIsDragEnabled(?!\w)', 'Qt.ItemFlag.ItemIsDragEnabled', 'Qt.ItemIsDragEnabled'),
        (r'(?<!\w)Qt\.ItemIsDropEnabled(?!\w)', 'Qt.ItemFlag.ItemIsDropEnabled', 'Qt.ItemIsDropEnabled'),

        # --- WindowModality ---
        (r'(?<!\w)Qt\.WindowModal(?!\w)', 'Qt.WindowModality.WindowModal', 'Qt.WindowModal'),
        (r'(?<!\w)Qt\.ApplicationModal(?!\w)', 'Qt.WindowModality.ApplicationModal', 'Qt.ApplicationModal'),
        (r'(?<!\w)Qt\.NonModal(?!\w)', 'Qt.WindowModality.NonModal', 'Qt.NonModal'),

        # --- WindowType / WindowFlags ---
        (r'(?<!\w)Qt\.Window(?![a-zA-Z])', 'Qt.WindowType.Window', 'Qt.Window'),
        (r'(?<!\w)Qt\.Dialog(?!\w)', 'Qt.WindowType.Dialog', 'Qt.Dialog'),
        (r'(?<!\w)Qt\.WindowStaysOnTopHint(?!\w)', 'Qt.WindowType.WindowStaysOnTopHint', 'Qt.WindowStaysOnTopHint'),
        (r'(?<!\w)Qt\.WindowCloseButtonHint(?!\w)', 'Qt.WindowType.WindowCloseButtonHint', 'Qt.WindowCloseButtonHint'),
        (r'(?<!\w)Qt\.WindowContextHelpButtonHint(?!\w)', 'Qt.WindowType.WindowContextHelpButtonHint', 'Qt.WindowContextHelpButtonHint'),
        (r'(?<!\w)Qt\.FramelessWindowHint(?!\w)', 'Qt.WindowType.FramelessWindowHint', 'Qt.FramelessWindowHint'),
        (r'(?<!\w)Qt\.CustomizeWindowHint(?!\w)', 'Qt.WindowType.CustomizeWindowHint', 'Qt.CustomizeWindowHint'),

        # --- SortOrder ---
        (r'(?<!\w)Qt\.AscendingOrder(?!\w)', 'Qt.SortOrder.AscendingOrder', 'Qt.AscendingOrder'),
        (r'(?<!\w)Qt\.DescendingOrder(?!\w)', 'Qt.SortOrder.DescendingOrder', 'Qt.DescendingOrder'),

        # --- TextFormat ---
        (r'(?<!\w)Qt\.RichText(?!\w)', 'Qt.TextFormat.RichText', 'Qt.RichText'),
        (r'(?<!\w)Qt\.PlainText(?!\w)', 'Qt.TextFormat.PlainText', 'Qt.PlainText'),

        # --- FocusPolicy ---
        (r'(?<!\w)Qt\.StrongFocus(?!\w)', 'Qt.FocusPolicy.StrongFocus', 'Qt.StrongFocus'),
        (r'(?<!\w)Qt\.NoFocus(?!\w)', 'Qt.FocusPolicy.NoFocus', 'Qt.NoFocus'),

        # --- ScrollBarPolicy ---
        (r'(?<!\w)Qt\.ScrollBarAlwaysOff(?!\w)', 'Qt.ScrollBarPolicy.ScrollBarAlwaysOff', 'Qt.ScrollBarAlwaysOff'),
        (r'(?<!\w)Qt\.ScrollBarAsNeeded(?!\w)', 'Qt.ScrollBarPolicy.ScrollBarAsNeeded', 'Qt.ScrollBarAsNeeded'),

        # --- ToolButtonStyle ---
        (r'(?<!\w)Qt\.ToolButtonTextBesideIcon(?!\w)', 'Qt.ToolButtonStyle.ToolButtonTextBesideIcon', 'Qt.ToolButtonTextBesideIcon'),
        (r'(?<!\w)Qt\.ToolButtonIconOnly(?!\w)', 'Qt.ToolButtonStyle.ToolButtonIconOnly', 'Qt.ToolButtonIconOnly'),
    ]

    # ----------------------------------------------------------------
    # QWidgets / QGui enum scoping
    # ----------------------------------------------------------------
    WIDGET_ENUM_PATTERNS: List[Tuple[str, str, str]] = [
        # --- QMessageBox.StandardButton ---
        (r'QMessageBox\.Ok(?!\w)', 'QMessageBox.StandardButton.Ok', 'QMessageBox.Ok'),
        (r'QMessageBox\.Cancel(?!\w)', 'QMessageBox.StandardButton.Cancel', 'QMessageBox.Cancel'),
        (r'QMessageBox\.Yes(?!\w)', 'QMessageBox.StandardButton.Yes', 'QMessageBox.Yes'),
        (r'QMessageBox\.No(?!\w)', 'QMessageBox.StandardButton.No', 'QMessageBox.No'),
        (r'QMessageBox\.Save(?!\w)', 'QMessageBox.StandardButton.Save', 'QMessageBox.Save'),
        (r'QMessageBox\.Discard(?!\w)', 'QMessageBox.StandardButton.Discard', 'QMessageBox.Discard'),
        (r'QMessageBox\.Open(?!\w)', 'QMessageBox.StandardButton.Open', 'QMessageBox.Open'),
        (r'QMessageBox\.Close(?!\w)', 'QMessageBox.StandardButton.Close', 'QMessageBox.Close'),
        (r'QMessageBox\.Abort(?!\w)', 'QMessageBox.StandardButton.Abort', 'QMessageBox.Abort'),
        (r'QMessageBox\.Retry(?!\w)', 'QMessageBox.StandardButton.Retry', 'QMessageBox.Retry'),
        (r'QMessageBox\.Ignore(?!\w)', 'QMessageBox.StandardButton.Ignore', 'QMessageBox.Ignore'),

        # --- QMessageBox.Icon ---
        (r'QMessageBox\.Warning(?!\w)', 'QMessageBox.Icon.Warning', 'QMessageBox.Warning'),
        (r'QMessageBox\.Critical(?!\w)', 'QMessageBox.Icon.Critical', 'QMessageBox.Critical'),
        (r'QMessageBox\.Information(?!\w)', 'QMessageBox.Icon.Information', 'QMessageBox.Information'),
        (r'QMessageBox\.Question(?!\w)', 'QMessageBox.Icon.Question', 'QMessageBox.Question'),

        # --- QDialogButtonBox.StandardButton ---
        (r'QDialogButtonBox\.Ok(?!\w)', 'QDialogButtonBox.StandardButton.Ok', 'QDialogButtonBox.Ok'),
        (r'QDialogButtonBox\.Cancel(?!\w)', 'QDialogButtonBox.StandardButton.Cancel', 'QDialogButtonBox.Cancel'),
        (r'QDialogButtonBox\.Close(?!\w)', 'QDialogButtonBox.StandardButton.Close', 'QDialogButtonBox.Close'),
        (r'QDialogButtonBox\.Apply(?!\w)', 'QDialogButtonBox.StandardButton.Apply', 'QDialogButtonBox.Apply'),
        (r'QDialogButtonBox\.Save(?!\w)', 'QDialogButtonBox.StandardButton.Save', 'QDialogButtonBox.Save'),

        # --- QFileDialog enums ---
        (r'QFileDialog\.AcceptOpen(?!\w)', 'QFileDialog.AcceptMode.AcceptOpen', 'QFileDialog.AcceptOpen'),
        (r'QFileDialog\.AcceptSave(?!\w)', 'QFileDialog.AcceptMode.AcceptSave', 'QFileDialog.AcceptSave'),
        (r'QFileDialog\.ExistingFile(?!\w)', 'QFileDialog.FileMode.ExistingFile', 'QFileDialog.ExistingFile'),
        (r'QFileDialog\.Directory(?!\w)', 'QFileDialog.FileMode.Directory', 'QFileDialog.Directory'),
        (r'QFileDialog\.AnyFile(?!\w)', 'QFileDialog.FileMode.AnyFile', 'QFileDialog.AnyFile'),
        (r'QFileDialog\.ExistingFiles(?!\w)', 'QFileDialog.FileMode.ExistingFiles', 'QFileDialog.ExistingFiles'),

        # --- QSizePolicy.Policy ---
        (r'QSizePolicy\.Expanding(?!\w)', 'QSizePolicy.Policy.Expanding', 'QSizePolicy.Expanding'),
        (r'QSizePolicy\.Fixed(?!\w)', 'QSizePolicy.Policy.Fixed', 'QSizePolicy.Fixed'),
        (r'QSizePolicy\.Minimum(?!\w)', 'QSizePolicy.Policy.Minimum', 'QSizePolicy.Minimum'),
        (r'QSizePolicy\.Maximum(?!\w)', 'QSizePolicy.Policy.Maximum', 'QSizePolicy.Maximum'),
        (r'QSizePolicy\.Preferred(?!\w)', 'QSizePolicy.Policy.Preferred', 'QSizePolicy.Preferred'),
        (r'QSizePolicy\.MinimumExpanding(?!\w)', 'QSizePolicy.Policy.MinimumExpanding', 'QSizePolicy.MinimumExpanding'),
        (r'QSizePolicy\.Ignored(?!\w)', 'QSizePolicy.Policy.Ignored', 'QSizePolicy.Ignored'),

        # --- QAbstractItemView ---
        (r'QAbstractItemView\.SelectRows(?!\w)', 'QAbstractItemView.SelectionBehavior.SelectRows', 'QAbstractItemView.SelectRows'),
        (r'QAbstractItemView\.SelectColumns(?!\w)', 'QAbstractItemView.SelectionBehavior.SelectColumns', 'QAbstractItemView.SelectColumns'),
        (r'QAbstractItemView\.SelectItems(?!\w)', 'QAbstractItemView.SelectionBehavior.SelectItems', 'QAbstractItemView.SelectItems'),
        (r'QAbstractItemView\.SingleSelection(?!\w)', 'QAbstractItemView.SelectionMode.SingleSelection', 'QAbstractItemView.SingleSelection'),
        (r'QAbstractItemView\.MultiSelection(?!\w)', 'QAbstractItemView.SelectionMode.MultiSelection', 'QAbstractItemView.MultiSelection'),
        (r'QAbstractItemView\.ExtendedSelection(?!\w)', 'QAbstractItemView.SelectionMode.ExtendedSelection', 'QAbstractItemView.ExtendedSelection'),
        (r'QAbstractItemView\.NoSelection(?!\w)', 'QAbstractItemView.SelectionMode.NoSelection', 'QAbstractItemView.NoSelection'),
        (r'QAbstractItemView\.NoEditTriggers(?!\w)', 'QAbstractItemView.EditTrigger.NoEditTriggers', 'QAbstractItemView.NoEditTriggers'),
        (r'QAbstractItemView\.DoubleClicked(?!\w)', 'QAbstractItemView.EditTrigger.DoubleClicked', 'QAbstractItemView.DoubleClicked'),

        # --- QHeaderView.ResizeMode ---
        (r'QHeaderView\.Stretch(?!\w)', 'QHeaderView.ResizeMode.Stretch', 'QHeaderView.Stretch'),
        (r'QHeaderView\.ResizeToContents(?!\w)', 'QHeaderView.ResizeMode.ResizeToContents', 'QHeaderView.ResizeToContents'),
        (r'QHeaderView\.Fixed(?!\w)', 'QHeaderView.ResizeMode.Fixed', 'QHeaderView.Fixed'),
        (r'QHeaderView\.Interactive(?!\w)', 'QHeaderView.ResizeMode.Interactive', 'QHeaderView.Interactive'),

        # --- QFrame.Shape / Shadow ---
        (r'QFrame\.HLine(?!\w)', 'QFrame.Shape.HLine', 'QFrame.HLine'),
        (r'QFrame\.VLine(?!\w)', 'QFrame.Shape.VLine', 'QFrame.VLine'),
        (r'QFrame\.StyledPanel(?!\w)', 'QFrame.Shape.StyledPanel', 'QFrame.StyledPanel'),
        (r'QFrame\.NoFrame(?!\w)', 'QFrame.Shape.NoFrame', 'QFrame.NoFrame'),
        (r'QFrame\.Box(?!\w)', 'QFrame.Shape.Box', 'QFrame.Box'),
        (r'QFrame\.Sunken(?!\w)', 'QFrame.Shadow.Sunken', 'QFrame.Sunken'),
        (r'QFrame\.Raised(?!\w)', 'QFrame.Shadow.Raised', 'QFrame.Raised'),
        (r'QFrame\.Plain(?!\w)', 'QFrame.Shadow.Plain', 'QFrame.Plain'),

        # --- QFont.Weight ---
        (r'QFont\.Thin(?!\w)', 'QFont.Weight.Thin', 'QFont.Thin'),
        (r'QFont\.Light(?!\w)', 'QFont.Weight.Light', 'QFont.Light'),
        (r'QFont\.Normal(?!\w)', 'QFont.Weight.Normal', 'QFont.Normal'),
        (r'QFont\.DemiBold(?!\w)', 'QFont.Weight.DemiBold', 'QFont.DemiBold'),
        (r'QFont\.Bold(?!\w)', 'QFont.Weight.Bold', 'QFont.Bold'),
        (r'QFont\.Black(?!\w)', 'QFont.Weight.Black', 'QFont.Black'),

        # --- QTabWidget.TabPosition ---
        (r'QTabWidget\.North(?!\w)', 'QTabWidget.TabPosition.North', 'QTabWidget.North'),
        (r'QTabWidget\.South(?!\w)', 'QTabWidget.TabPosition.South', 'QTabWidget.South'),

        # --- QLineEdit.EchoMode ---
        (r'QLineEdit\.Password(?!\w)', 'QLineEdit.EchoMode.Password', 'QLineEdit.Password'),
        (r'QLineEdit\.Normal(?!\w)', 'QLineEdit.EchoMode.Normal', 'QLineEdit.Normal'),
    ]

    # ----------------------------------------------------------------
    # QVariant type constants (QVariant.X -> QMetaType.Type.X)
    # ----------------------------------------------------------------
    QVARIANT_TYPE_PATTERNS: List[Tuple[str, str, str]] = [
        (r'QVariant\.String(?!\w)', 'QMetaType.Type.QString', 'QVariant.String'),
        (r'QVariant\.Int(?!\w)', 'QMetaType.Type.Int', 'QVariant.Int'),
        (r'QVariant\.Double(?!\w)', 'QMetaType.Type.Double', 'QVariant.Double'),
        (r'QVariant\.Bool(?!\w)', 'QMetaType.Type.Bool', 'QVariant.Bool'),
        (r'QVariant\.LongLong(?!\w)', 'QMetaType.Type.LongLong', 'QVariant.LongLong'),
        (r'QVariant\.Date(?!Time)(?!\w)', 'QMetaType.Type.QDate', 'QVariant.Date'),
        (r'QVariant\.DateTime(?!\w)', 'QMetaType.Type.QDateTime', 'QVariant.DateTime'),
        (r'QVariant\.Invalid(?!\w)', 'QMetaType.Type.UnknownType', 'QVariant.Invalid'),
        (r'QVariant\.ByteArray(?!\w)', 'QMetaType.Type.QByteArray', 'QVariant.ByteArray'),
    ]

    # ----------------------------------------------------------------
    # QGIS-specific deprecated patterns (removed in QGIS 4.0)
    # ----------------------------------------------------------------
    QGIS_DEPRECATED_PATTERNS: List[Tuple[str, str, str]] = [
        # --- QgsWkbTypes geometry types -> Qgis.GeometryType ---
        (r'QgsWkbTypes\.PolygonGeometry(?!\w)', 'Qgis.GeometryType.Polygon', 'QgsWkbTypes.PolygonGeometry'),
        (r'QgsWkbTypes\.LineGeometry(?!\w)', 'Qgis.GeometryType.Line', 'QgsWkbTypes.LineGeometry'),
        (r'QgsWkbTypes\.PointGeometry(?!\w)', 'Qgis.GeometryType.Point', 'QgsWkbTypes.PointGeometry'),
        (r'QgsWkbTypes\.NullGeometry(?!\w)', 'Qgis.GeometryType.Null', 'QgsWkbTypes.NullGeometry'),
        (r'QgsWkbTypes\.UnknownGeometry(?!\w)', 'Qgis.GeometryType.Unknown', 'QgsWkbTypes.UnknownGeometry'),

        # --- QgsWkbTypes WKB constants -> Qgis.WkbType ---
        (r'QgsWkbTypes\.Point(?!\w)', 'Qgis.WkbType.Point', 'QgsWkbTypes.Point'),
        (r'QgsWkbTypes\.LineString(?!\w)', 'Qgis.WkbType.LineString', 'QgsWkbTypes.LineString'),
        (r'QgsWkbTypes\.Polygon(?!\w)', 'Qgis.WkbType.Polygon', 'QgsWkbTypes.Polygon'),
        (r'QgsWkbTypes\.MultiPoint(?!\w)', 'Qgis.WkbType.MultiPoint', 'QgsWkbTypes.MultiPoint'),
        (r'QgsWkbTypes\.MultiLineString(?!\w)', 'Qgis.WkbType.MultiLineString', 'QgsWkbTypes.MultiLineString'),
        (r'QgsWkbTypes\.MultiPolygon(?!\w)', 'Qgis.WkbType.MultiPolygon', 'QgsWkbTypes.MultiPolygon'),
        (r'QgsWkbTypes\.NoGeometry(?!\w)', 'Qgis.WkbType.NoGeometry', 'QgsWkbTypes.NoGeometry'),
        (r'QgsWkbTypes\.MultiPolygonM(?!\w)', 'Qgis.WkbType.MultiPolygonM', 'QgsWkbTypes.MultiPolygonM'),
        (r'QgsWkbTypes\.MultiLineStringM(?!\w)', 'Qgis.WkbType.MultiLineStringM', 'QgsWkbTypes.MultiLineStringM'),
        (r'QgsWkbTypes\.MultiPointM(?!\w)', 'Qgis.WkbType.MultiPointM', 'QgsWkbTypes.MultiPointM'),
        (r'QgsWkbTypes\.PolygonZ(?!\w)', 'Qgis.WkbType.PolygonZ', 'QgsWkbTypes.PolygonZ'),
        (r'QgsWkbTypes\.MultiPolygonZ(?!\w)', 'Qgis.WkbType.MultiPolygonZ', 'QgsWkbTypes.MultiPolygonZ'),

        # --- QgsWkbTypes static methods -> Qgis.WkbType or QgsWkbTypes ---
        (r'QgsWkbTypes\.geometryType\(', 'QgsWkbTypes.geometryType( [deprecated]', 'QgsWkbTypes.geometryType()'),
        (r'QgsWkbTypes\.displayString\(', 'QgsWkbTypes.displayString( [deprecated]', 'QgsWkbTypes.displayString()'),
        (r'QgsWkbTypes\.hasZ\(', 'QgsWkbTypes.hasZ( [deprecated]', 'QgsWkbTypes.hasZ()'),
        (r'QgsWkbTypes\.hasM\(', 'QgsWkbTypes.hasM( [deprecated]', 'QgsWkbTypes.hasM()'),
        (r'QgsWkbTypes\.dropZ\(', 'QgsWkbTypes.dropZ( [deprecated]', 'QgsWkbTypes.dropZ()'),
        (r'QgsWkbTypes\.dropM\(', 'QgsWkbTypes.dropM( [deprecated]', 'QgsWkbTypes.dropM()'),
        (r'QgsWkbTypes\.isSingleType\(', 'QgsWkbTypes.isSingleType( [deprecated]', 'QgsWkbTypes.isSingleType()'),
        (r'QgsWkbTypes\.isMultiType\(', 'QgsWkbTypes.isMultiType( [deprecated]', 'QgsWkbTypes.isMultiType()'),
        (r'QgsWkbTypes\.flatType\(', 'QgsWkbTypes.flatType( [deprecated]', 'QgsWkbTypes.flatType()'),

        # --- QgsUnitTypes -> Qgis.*Unit ---
        (r'QgsUnitTypes\.RenderMillimeters(?!\w)', 'Qgis.RenderUnit.Millimeters', 'QgsUnitTypes.RenderMillimeters'),
        (r'QgsUnitTypes\.RenderMapUnits(?!\w)', 'Qgis.RenderUnit.MapUnits', 'QgsUnitTypes.RenderMapUnits'),
        (r'QgsUnitTypes\.RenderPixels(?!\w)', 'Qgis.RenderUnit.Pixels', 'QgsUnitTypes.RenderPixels'),
        (r'QgsUnitTypes\.RenderPoints(?!\w)', 'Qgis.RenderUnit.Points', 'QgsUnitTypes.RenderPoints'),
        (r'QgsUnitTypes\.RenderPercentage(?!\w)', 'Qgis.RenderUnit.Percentage', 'QgsUnitTypes.RenderPercentage'),
        (r'QgsUnitTypes\.RenderInches(?!\w)', 'Qgis.RenderUnit.Inches', 'QgsUnitTypes.RenderInches'),
        (r'QgsUnitTypes\.LayoutMillimeters(?!\w)', 'Qgis.LayoutUnit.Millimeters', 'QgsUnitTypes.LayoutMillimeters'),
        (r'QgsUnitTypes\.LayoutCentimeters(?!\w)', 'Qgis.LayoutUnit.Centimeters', 'QgsUnitTypes.LayoutCentimeters'),
        (r'QgsUnitTypes\.LayoutPixels(?!\w)', 'Qgis.LayoutUnit.Pixels', 'QgsUnitTypes.LayoutPixels'),
        (r'QgsUnitTypes\.LayoutPoints(?!\w)', 'Qgis.LayoutUnit.Points', 'QgsUnitTypes.LayoutPoints'),
        (r'QgsUnitTypes\.LayoutInches(?!\w)', 'Qgis.LayoutUnit.Inches', 'QgsUnitTypes.LayoutInches'),
        (r'QgsUnitTypes\.DistanceMeters(?!\w)', 'Qgis.DistanceUnit.Meters', 'QgsUnitTypes.DistanceMeters'),
        (r'QgsUnitTypes\.DistanceKilometers(?!\w)', 'Qgis.DistanceUnit.Kilometers', 'QgsUnitTypes.DistanceKilometers'),
        (r'QgsUnitTypes\.AreaSquareMeters(?!\w)', 'Qgis.AreaUnit.SquareMeters', 'QgsUnitTypes.AreaSquareMeters'),
        (r'QgsUnitTypes\.AreaHectares(?!\w)', 'Qgis.AreaUnit.Hectares', 'QgsUnitTypes.AreaHectares'),

        # --- QgsMapLayer enums ---
        (r'QgsMapLayer\.VectorLayer(?!\w)', 'Qgis.LayerType.Vector', 'QgsMapLayer.VectorLayer'),
        (r'QgsMapLayer\.RasterLayer(?!\w)', 'Qgis.LayerType.Raster', 'QgsMapLayer.RasterLayer'),
    ]

    # ----------------------------------------------------------------
    # Классы, перемещённые между Qt модулями
    # ----------------------------------------------------------------
    RELOCATED_CLASSES = {
        'QAction': ('QtWidgets', 'QtGui'),
        'QShortcut': ('QtWidgets', 'QtGui'),
        'QActionGroup': ('QtWidgets', 'QtGui'),
    }

    # ----------------------------------------------------------------
    # Deprecated методы (удалены в PyQt6)
    # ----------------------------------------------------------------
    DEPRECATED_METHODS = [
        (r'\.exec_\(\)', '.exec()', 'exec_() -> exec()'),
        (r'\.print_\(\)', '.print()', 'print_() -> print()'),
    ]

    # ----------------------------------------------------------------
    # Удалённые глобальные объекты
    # ----------------------------------------------------------------
    REMOVED_GLOBALS = [
        (r'\bqApp\b', 'QApplication.instance()', 'qApp -> QApplication.instance()'),
        (r'PYQT_CONFIGURATION', 'Удалён', 'PYQT_CONFIGURATION'),
    ]

    # ----------------------------------------------------------------
    # Удалённые модули Qt
    # ----------------------------------------------------------------
    REMOVED_MODULES = [
        'QtScript',
        'QtScriptTools',
        'QtWebKit',
        'QtWebKitWidgets',
        'QtMultimedia',
        'QtMultimediaWidgets',
    ]

    def __init__(self, iface: Any, logger: Any) -> None:
        """Инициализация теста"""
        self.iface = iface
        self.logger = logger
        self.plugin_root = self._get_plugin_root()
        self.issues: List[Dict[str, Any]] = []
        self._python_files_cache: List[Path] = []

    def _get_plugin_root(self) -> str:
        """Получить корневую папку плагина"""
        current = os.path.dirname(__file__)
        for _ in range(4):
            current = os.path.dirname(current)
        return current

    def run_all_tests(self) -> None:
        """Запуск всех тестов совместимости Qt6"""
        self.logger.section("ТЕСТ СОВМЕСТИМОСТИ С Qt6/QGIS 4.0")

        try:
            # Статический анализ (regex-сканирование кода)
            self.test_01_check_metadata()
            self.test_02_check_imports()
            self.test_03_check_qt_enum_scoping()
            self.test_04_check_widget_enum_scoping()
            self.test_05_check_qvariant_types()
            self.test_06_check_qvariant_constructor()
            self.test_07_check_deprecated_methods()
            self.test_08_check_relocated_classes()
            self.test_09_check_removed_globals()
            self.test_10_check_removed_modules()
            self.test_11_check_qgis_deprecated()

            # Runtime проверки (среда выполнения)
            self.test_13_runtime_enum_resolution()
            self.test_14_runtime_method_existence()
            self.test_15_runtime_qvariant_behavior()
            self.test_16_runtime_processing_algorithms()
            self.test_17_runtime_third_party_libs()

            # Итоговая сводка
            self.test_12_summary()

        except Exception as e:
            self.logger.error(f"Критическая ошибка тестов Qt6: {str(e)}")

        self.logger.summary()

    # ----------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------

    def _get_python_files(self) -> List[Path]:
        """Получить все Python файлы плагина (с кэшированием)"""
        if self._python_files_cache:
            return self._python_files_cache

        plugin_path = Path(self.plugin_root)
        exclude_dirs = {
            '__pycache__', '.git', '.vscode', 'external_modules',
            'node_modules', 'scripts'
        }

        for py_file in plugin_path.rglob('*.py'):
            if any(excluded in py_file.parts for excluded in exclude_dirs):
                continue
            self._python_files_cache.append(py_file)

        return self._python_files_cache

    def _is_this_test_file(self, py_file: Path) -> bool:
        """Проверить, является ли файл текущим тестом (исключаем себя)"""
        return py_file.name == 'Fsm_4_2_T_qt6_compatibility.py'

    def _scan_files_for_patterns(
        self,
        patterns: List[Tuple[str, str, str]],
        skip_self: bool = True,
    ) -> Dict[str, List[Tuple[str, int, str]]]:
        """Сканировать файлы по списку regex-паттернов.

        Returns:
            Dict[description, List[(rel_path, line_num, line_text)]]
        """
        results: Dict[str, List[Tuple[str, int, str]]] = {}

        for py_file in self._get_python_files():
            if skip_self and self._is_this_test_file(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception:
                continue

            rel_path = str(py_file.relative_to(self.plugin_root))

            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                # Пропускаем комментарии и строки-литералы
                if stripped.startswith('#'):
                    continue
                if stripped.startswith(("'", '"', "r'", 'r"', "f'", 'f"')):
                    continue

                for pattern, _replacement, description in patterns:
                    if re.search(pattern, line):
                        if description not in results:
                            results[description] = []
                        results[description].append(
                            (rel_path, line_num, stripped[:80])
                        )

        return results

    def _report_pattern_results(
        self,
        results: Dict[str, List[Tuple[str, int, str]]],
        severity: str = 'warning',
        show_all_types: bool = True,
        show_files_per_type: int = 3,
    ) -> int:
        """Вывести результаты сканирования паттернов.

        Returns:
            Общее кол-во найденных вхождений
        """
        if not results:
            return 0

        total = sum(len(v) for v in results.values())

        items = list(results.items()) if show_all_types else list(results.items())[:10]

        for description, occurrences in items:
            files = sorted(set(o[0] for o in occurrences))
            self.logger.info(f"  {description}: {len(occurrences)} [{len(files)} файлов]")

            for file_path, line_num, line_text in occurrences[:show_files_per_type]:
                self.logger.info(f"    {file_path}:{line_num}")

            if len(occurrences) > show_files_per_type:
                self.logger.info(f"    ... и ещё {len(occurrences) - show_files_per_type}")

            self.issues.append({
                'issue': description,
                'count': len(occurrences),
                'files': files,
                'severity': severity,
            })

        return total

    # ----------------------------------------------------------------
    # ТЕСТ 1: metadata.txt
    # ----------------------------------------------------------------

    def test_01_check_metadata(self) -> None:
        """ТЕСТ 1: Проверка metadata.txt"""
        self.logger.section("1. Проверка metadata.txt")

        metadata_path = os.path.join(self.plugin_root, 'metadata.txt')

        if not os.path.exists(metadata_path):
            self.logger.warning("metadata.txt не найден")
            return

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # supportsQt6
            if 'supportsQt6=True' in content:
                self.logger.success("supportsQt6=True установлен")
            elif 'supportsQt6' in content:
                self.logger.warning("supportsQt6 найден, но не True")
            else:
                self.logger.warning("supportsQt6 не указан (добавьте supportsQt6=True)")
                self.issues.append({
                    'file': 'metadata.txt',
                    'issue': 'Отсутствует supportsQt6=True',
                    'severity': 'warning',
                })

            # qgisMaximumVersion
            max_match = re.search(r'qgisMaximumVersion=(\d+\.\d+)', content)
            if max_match:
                max_ver = max_match.group(1)
                if float(max_ver) >= 4.99:
                    self.logger.success(f"qgisMaximumVersion={max_ver} (QGIS 4 ready)")
                else:
                    self.logger.warning(f"qgisMaximumVersion={max_ver} (обновите до 4.99)")
            else:
                self.logger.info("qgisMaximumVersion не указан")

        except Exception as e:
            self.logger.error(f"Ошибка чтения metadata.txt: {e}")

    # ----------------------------------------------------------------
    # ТЕСТ 2: Прямые импорты PyQt5/PyQt6
    # ----------------------------------------------------------------

    def test_02_check_imports(self) -> None:
        """ТЕСТ 2: Проверка импортов PyQt"""
        self.logger.section("2. Проверка импортов PyQt5/PyQt6")

        direct_imports: List[Tuple[str, int, str]] = []

        for py_file in self._get_python_files():
            if self._is_this_test_file(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception:
                continue

            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if re.search(r'from PyQt[56]\.', stripped) or re.search(r'import PyQt[56]', stripped):
                    rel_path = str(py_file.relative_to(self.plugin_root))
                    direct_imports.append((rel_path, line_num, stripped))

        if direct_imports:
            self.logger.warning(f"Найдено {len(direct_imports)} прямых импортов PyQt5/PyQt6")
            for file_path, line_num, line in direct_imports:
                self.logger.info(f"  {file_path}:{line_num} - {line[:60]}")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': f'Прямой импорт: {line[:50]}',
                    'fix': 'from qgis.PyQt...',
                    'severity': 'error',
                })
        else:
            self.logger.success("Все импорты используют qgis.PyQt")

    # ----------------------------------------------------------------
    # ТЕСТ 3: Qt namespace enum scoping
    # ----------------------------------------------------------------

    def test_03_check_qt_enum_scoping(self) -> None:
        """ТЕСТ 3: Qt namespace enum scoping (Qt.X -> Qt.EnumClass.X)"""
        self.logger.section("3. Qt namespace enums (Qt.X -> Qt.EnumClass.X)")

        results = self._scan_files_for_patterns(self.QT_ENUM_PATTERNS)

        if results:
            total = self._report_pattern_results(results, severity='warning')
            self.logger.warning(f"Итого: {total} устаревших Qt enum паттернов")
        else:
            self.logger.success("Все Qt enum используют Qt6-совместимый синтаксис")

    # ----------------------------------------------------------------
    # ТЕСТ 4: Widget enum scoping
    # ----------------------------------------------------------------

    def test_04_check_widget_enum_scoping(self) -> None:
        """ТЕСТ 4: Widget enum scoping (QMessageBox.Yes -> QMessageBox.StandardButton.Yes)"""
        self.logger.section("4. Widget enums (QWidget.X -> QWidget.EnumClass.X)")

        results = self._scan_files_for_patterns(self.WIDGET_ENUM_PATTERNS)

        if results:
            total = self._report_pattern_results(results, severity='warning')
            self.logger.warning(f"Итого: {total} устаревших widget enum паттернов")
        else:
            self.logger.success("Все widget enum используют Qt6-совместимый синтаксис")

    # ----------------------------------------------------------------
    # ТЕСТ 5: QVariant type constants
    # ----------------------------------------------------------------

    def test_05_check_qvariant_types(self) -> None:
        """ТЕСТ 5: QVariant.X -> QMetaType.Type.X"""
        self.logger.section("5. QVariant типы (-> QMetaType.Type)")

        results = self._scan_files_for_patterns(self.QVARIANT_TYPE_PATTERNS)

        if results:
            total = self._report_pattern_results(results, severity='error')
            self.logger.error(f"Итого: {total} использований QVariant типов")
        else:
            self.logger.success("QVariant типы не используются (QMetaType.Type)")

    # ----------------------------------------------------------------
    # ТЕСТ 6: QVariant() конструктор
    # ----------------------------------------------------------------

    def test_06_check_qvariant_constructor(self) -> None:
        """ТЕСТ 6: QVariant() конструктор -> None"""
        self.logger.section("6. QVariant() конструктор (-> None)")

        pattern = r'QVariant\(\)'
        issues: List[Tuple[str, int, str]] = []

        for py_file in self._get_python_files():
            if self._is_this_test_file(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception:
                continue

            rel_path = str(py_file.relative_to(self.plugin_root))

            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if stripped.startswith(("'", '"', "r'", 'r"', "f'", 'f"')):
                    continue
                if re.search(pattern, line):
                    issues.append((rel_path, line_num, stripped[:80]))

        if issues:
            self.logger.warning(f"Найдено {len(issues)} использований QVariant()")
            for file_path, line_num, line_text in issues:
                self.logger.info(f"  {file_path}:{line_num} - {line_text}")
            self.issues.append({
                'issue': 'QVariant() -> None',
                'count': len(issues),
                'severity': 'warning',
            })
        else:
            self.logger.success("QVariant() конструктор не используется")

    # ----------------------------------------------------------------
    # ТЕСТ 7: Deprecated методы (exec_(), print_())
    # ----------------------------------------------------------------

    def test_07_check_deprecated_methods(self) -> None:
        """ТЕСТ 7: Deprecated методы (exec_(), print_())"""
        self.logger.section("7. Deprecated методы (exec_(), print_())")

        results = self._scan_files_for_patterns(
            [(p, r, d) for p, r, d in self.DEPRECATED_METHODS]
        )

        if results:
            total = self._report_pattern_results(
                results, severity='warning', show_files_per_type=5
            )
            self.logger.warning(f"Итого: {total} deprecated вызовов")
        else:
            self.logger.success("Deprecated методы не используются")

    # ----------------------------------------------------------------
    # ТЕСТ 8: Перемещённые классы
    # ----------------------------------------------------------------

    def test_08_check_relocated_classes(self) -> None:
        """ТЕСТ 8: Перемещённые классы (QAction: QtWidgets -> QtGui)"""
        self.logger.section("8. Перемещённые классы (QtWidgets -> QtGui)")

        relocation_issues: List[Tuple[str, int, str, str]] = []

        for py_file in self._get_python_files():
            if self._is_this_test_file(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception:
                continue

            for line_num, line in enumerate(lines, 1):
                for class_name, (old_module, new_module) in self.RELOCATED_CLASSES.items():
                    pattern = rf'from\s+(?:qgis\.)?PyQt\.{old_module}\s+import\s+.*\b{class_name}\b'
                    if re.search(pattern, line):
                        rel_path = str(py_file.relative_to(self.plugin_root))
                        relocation_issues.append(
                            (rel_path, line_num, class_name, f'{old_module} -> {new_module}')
                        )

        if relocation_issues:
            self.logger.warning(f"Найдено {len(relocation_issues)} импортов перемещённых классов")
            for file_path, line_num, class_name, move in relocation_issues:
                self.logger.info(f"  {file_path}:{line_num} - {class_name} ({move})")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': f'{class_name}: {move}',
                    'severity': 'info',
                })
        else:
            self.logger.success("Перемещённые классы корректно импортированы")

    # ----------------------------------------------------------------
    # ТЕСТ 9: Удалённые глобальные объекты
    # ----------------------------------------------------------------

    def test_09_check_removed_globals(self) -> None:
        """ТЕСТ 9: Удалённые глобальные объекты (qApp)"""
        self.logger.section("9. Удалённые глобальные объекты (qApp)")

        results = self._scan_files_for_patterns(
            [(p, r, d) for p, r, d in self.REMOVED_GLOBALS]
        )

        if results:
            total = self._report_pattern_results(results, severity='error')
            self.logger.error(f"Итого: {total} использований удалённых объектов")
        else:
            self.logger.success("Удалённые глобальные объекты не используются")

    # ----------------------------------------------------------------
    # ТЕСТ 10: Удалённые модули Qt
    # ----------------------------------------------------------------

    def test_10_check_removed_modules(self) -> None:
        """ТЕСТ 10: Удалённые модули Qt"""
        self.logger.section("10. Удалённые модули Qt")

        module_issues: List[Tuple[str, int, str]] = []

        for py_file in self._get_python_files():
            if self._is_this_test_file(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            except Exception:
                continue

            for line_num, line in enumerate(lines, 1):
                if line.strip().startswith('#'):
                    continue
                for module in self.REMOVED_MODULES:
                    if re.search(rf'from\s+.*{module}\s+import', line) or \
                       re.search(rf'import\s+.*{module}', line):
                        rel_path = str(py_file.relative_to(self.plugin_root))
                        module_issues.append((rel_path, line_num, module))

        if module_issues:
            self.logger.error(f"Найдено {len(module_issues)} импортов удалённых модулей")
            for file_path, line_num, module in module_issues:
                self.logger.info(f"  {file_path}:{line_num} - {module}")
                self.issues.append({
                    'file': file_path,
                    'line': line_num,
                    'issue': f'Удалённый модуль: {module}',
                    'severity': 'error',
                })
        else:
            self.logger.success("Удалённые модули Qt не используются")

    # ----------------------------------------------------------------
    # ТЕСТ 11: QGIS-specific deprecated API
    # ----------------------------------------------------------------

    def test_11_check_qgis_deprecated(self) -> None:
        """ТЕСТ 11: QGIS deprecated API (QgsWkbTypes, QgsUnitTypes)"""
        self.logger.section("11. QGIS deprecated API (QgsWkbTypes, QgsUnitTypes)")

        results = self._scan_files_for_patterns(self.QGIS_DEPRECATED_PATTERNS)

        if results:
            total = self._report_pattern_results(results, severity='warning')
            self.logger.warning(f"Итого: {total} deprecated QGIS API вызовов")
        else:
            self.logger.success("QGIS deprecated API не используется")

    # ----------------------------------------------------------------
    # ТЕСТ 12: Итоговая сводка
    # ----------------------------------------------------------------

    # ----------------------------------------------------------------
    # ТЕСТ 13: Runtime enum resolution
    # ----------------------------------------------------------------

    def test_13_runtime_enum_resolution(self) -> None:
        """ТЕСТ 13: Проверка резолвинга Qt6 fully-qualified enum в runtime"""
        self.logger.section("13. Runtime: Qt6 enum resolution")

        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import (
            QMessageBox, QFrame, QSizePolicy, QAbstractItemView,
            QHeaderView, QDialogButtonBox
        )

        # --- Qt namespace enums ---
        qt_enums = [
            ('Qt.AlignmentFlag.AlignCenter', lambda: Qt.AlignmentFlag.AlignCenter),
            ('Qt.AlignmentFlag.AlignLeft', lambda: Qt.AlignmentFlag.AlignLeft),
            ('Qt.ItemDataRole.UserRole', lambda: Qt.ItemDataRole.UserRole),
            ('Qt.ItemDataRole.DisplayRole', lambda: Qt.ItemDataRole.DisplayRole),
            ('Qt.CursorShape.WaitCursor', lambda: Qt.CursorShape.WaitCursor),
            ('Qt.Orientation.Horizontal', lambda: Qt.Orientation.Horizontal),
            ('Qt.CheckState.Checked', lambda: Qt.CheckState.Checked),
            ('Qt.GlobalColor.white', lambda: Qt.GlobalColor.white),
            ('Qt.PenStyle.SolidLine', lambda: Qt.PenStyle.SolidLine),
            ('Qt.BrushStyle.SolidPattern', lambda: Qt.BrushStyle.SolidPattern),
            ('Qt.ItemFlag.ItemIsEnabled', lambda: Qt.ItemFlag.ItemIsEnabled),
            ('Qt.WindowModality.WindowModal', lambda: Qt.WindowModality.WindowModal),
            ('Qt.SortOrder.AscendingOrder', lambda: Qt.SortOrder.AscendingOrder),
            ('Qt.FocusPolicy.StrongFocus', lambda: Qt.FocusPolicy.StrongFocus),
            ('Qt.WindowType.Dialog', lambda: Qt.WindowType.Dialog),
        ]

        # --- Widget enums ---
        widget_enums = [
            ('QMessageBox.StandardButton.Yes', lambda: QMessageBox.StandardButton.Yes),
            ('QMessageBox.StandardButton.No', lambda: QMessageBox.StandardButton.No),
            ('QMessageBox.StandardButton.Ok', lambda: QMessageBox.StandardButton.Ok),
            ('QMessageBox.Icon.Warning', lambda: QMessageBox.Icon.Warning),
            ('QMessageBox.Icon.Critical', lambda: QMessageBox.Icon.Critical),
            ('QDialogButtonBox.StandardButton.Ok', lambda: QDialogButtonBox.StandardButton.Ok),
            ('QFrame.Shape.HLine', lambda: QFrame.Shape.HLine),
            ('QSizePolicy.Policy.Expanding', lambda: QSizePolicy.Policy.Expanding),
            ('QSizePolicy.Policy.Fixed', lambda: QSizePolicy.Policy.Fixed),
            ('QAbstractItemView.SelectionBehavior.SelectRows', lambda: QAbstractItemView.SelectionBehavior.SelectRows),
            ('QAbstractItemView.EditTrigger.NoEditTriggers', lambda: QAbstractItemView.EditTrigger.NoEditTriggers),
            ('QHeaderView.ResizeMode.Stretch', lambda: QHeaderView.ResizeMode.Stretch),
        ]

        # --- QGIS enums ---
        qgis_enums: List[Tuple[str, Any]] = []
        try:
            from qgis.core import Qgis
            qgis_enums = [
                ('Qgis.GeometryType.Polygon', lambda: Qgis.GeometryType.Polygon),
                ('Qgis.GeometryType.Line', lambda: Qgis.GeometryType.Line),
                ('Qgis.GeometryType.Point', lambda: Qgis.GeometryType.Point),
                ('Qgis.WkbType.MultiPolygon', lambda: Qgis.WkbType.MultiPolygon),
                ('Qgis.WkbType.Point', lambda: Qgis.WkbType.Point),
                ('Qgis.WkbType.NoGeometry', lambda: Qgis.WkbType.NoGeometry),
                ('Qgis.LayerType.Vector', lambda: Qgis.LayerType.Vector),
                ('Qgis.LayerType.Raster', lambda: Qgis.LayerType.Raster),
            ]
        except Exception:
            self.logger.info("Qgis enum класс недоступен (ожидаемо для старых версий)")

        all_enums = [
            ('Qt namespace', qt_enums),
            ('Widget', widget_enums),
            ('QGIS', qgis_enums),
        ]

        total_ok = 0
        total_fail = 0

        for group_name, enum_list in all_enums:
            if not enum_list:
                continue

            ok_count = 0
            fail_list = []

            for name, resolver in enum_list:
                try:
                    resolver()
                    ok_count += 1
                except AttributeError:
                    fail_list.append(name)

            total_ok += ok_count
            total_fail += len(fail_list)

            if fail_list:
                self.logger.warning(
                    f"  {group_name}: {ok_count}/{ok_count + len(fail_list)} "
                    f"(не резолвятся: {', '.join(fail_list[:5])})"
                )
                for name in fail_list:
                    self.issues.append({
                        'issue': f'Runtime enum fail: {name}',
                        'count': 1,
                        'severity': 'warning',
                    })
            else:
                self.logger.success(f"  {group_name}: все {ok_count} enum резолвятся")

        if total_fail == 0:
            self.logger.success(
                f"Все {total_ok} Qt6 fully-qualified enum доступны в runtime"
            )
        else:
            self.logger.warning(
                f"Runtime enum: {total_ok} OK, {total_fail} недоступны"
            )

    # ----------------------------------------------------------------
    # ТЕСТ 14: Runtime method existence
    # ----------------------------------------------------------------

    def test_14_runtime_method_existence(self) -> None:
        """ТЕСТ 14: Проверка наличия методов, изменённых в Qt6"""
        self.logger.section("14. Runtime: method existence (Qt5/Qt6)")

        # --- exec vs exec_ ---
        from qgis.PyQt.QtWidgets import QDialog

        dialog = QDialog()
        has_exec = hasattr(dialog, 'exec')
        has_exec_ = hasattr(dialog, 'exec_')
        dialog.deleteLater()

        if has_exec and has_exec_:
            self.logger.success("QDialog: exec() и exec_() оба доступны (совместимый режим)")
        elif has_exec:
            self.logger.success("QDialog: exec() доступен (Qt6 стиль)")
            if not has_exec_:
                self.logger.warning("QDialog: exec_() отсутствует (deprecated, удалён в Qt6)")
                self.issues.append({
                    'issue': 'exec_() недоступен в runtime',
                    'count': 1,
                    'severity': 'warning',
                })
        elif has_exec_:
            self.logger.info("QDialog: только exec_() доступен (Qt5 стиль)")
        else:
            self.logger.error("QDialog: ни exec() ни exec_() не доступны!")

        # --- QAction: QtGui vs QtWidgets ---
        action_from_gui = False
        action_from_widgets = False

        try:
            from qgis.PyQt.QtGui import QAction  # noqa: F401
            action_from_gui = True
        except ImportError:
            pass

        try:
            from qgis.PyQt.QtWidgets import QAction as _QAction  # noqa: F401
            action_from_widgets = True
        except ImportError:
            pass

        if action_from_gui and action_from_widgets:
            self.logger.success("QAction: доступен из QtGui и QtWidgets (совместимый режим)")
        elif action_from_gui:
            self.logger.success("QAction: доступен из QtGui (Qt6 стиль)")
        elif action_from_widgets:
            self.logger.info("QAction: доступен только из QtWidgets (Qt5 стиль)")
        else:
            self.logger.error("QAction: недоступен ни из QtGui ни из QtWidgets!")

        # --- QApplication.instance() vs qApp ---
        from qgis.PyQt.QtWidgets import QApplication

        has_instance = hasattr(QApplication, 'instance')
        self.logger.check(
            has_instance,
            "QApplication.instance() доступен",
            "QApplication.instance() недоступен!"
        )

        qapp_available = False
        try:
            from qgis.PyQt.QtWidgets import qApp  # noqa: F401
            qapp_available = True
        except ImportError:
            pass

        if qapp_available:
            self.logger.info("qApp доступен (deprecated в Qt6, но пока работает)")
        else:
            self.logger.success("qApp недоступен (ожидаемо для Qt6)")

    # ----------------------------------------------------------------
    # ТЕСТ 15: Runtime QVariant behavior
    # ----------------------------------------------------------------

    def test_15_runtime_qvariant_behavior(self) -> None:
        """ТЕСТ 15: Поведение QVariant в runtime"""
        self.logger.section("15. Runtime: QVariant behavior")

        # --- QVariant как класс ---
        qvariant_available = False
        try:
            from qgis.PyQt.QtCore import QVariant
            qvariant_available = True
            self.logger.info("QVariant класс доступен")
        except ImportError:
            self.logger.success("QVariant класс недоступен (ожидаемо для Qt6)")

        # --- QVariant() конструктор ---
        if qvariant_available:
            from qgis.PyQt.QtCore import QVariant
            try:
                val = QVariant()
                self.logger.info(f"QVariant() = {val} (тип: {type(val).__name__})")

                # NULL проверка
                is_null = val.isNull() if hasattr(val, 'isNull') else 'метод отсутствует'
                self.logger.info(f"QVariant().isNull() = {is_null}")

            except TypeError as e:
                self.logger.warning(f"QVariant() вызывает TypeError: {e}")
                self.issues.append({
                    'issue': 'QVariant() конструктор недоступен в runtime',
                    'count': 1,
                    'severity': 'warning',
                })
            except Exception as e:
                self.logger.warning(f"QVariant() ошибка: {e}")

        # --- QMetaType.Type доступность ---
        try:
            from qgis.PyQt.QtCore import QMetaType
            test_types = [
                ('QMetaType.Type.QString', lambda: QMetaType.Type.QString),
                ('QMetaType.Type.Int', lambda: QMetaType.Type.Int),
                ('QMetaType.Type.Double', lambda: QMetaType.Type.Double),
                ('QMetaType.Type.Bool', lambda: QMetaType.Type.Bool),
                ('QMetaType.Type.LongLong', lambda: QMetaType.Type.LongLong),
            ]

            ok_count = 0
            for name, resolver in test_types:
                try:
                    resolver()
                    ok_count += 1
                except AttributeError:
                    self.logger.warning(f"  {name} недоступен")

            if ok_count == len(test_types):
                self.logger.success(f"QMetaType.Type: все {ok_count} типов доступны")
            else:
                self.logger.warning(
                    f"QMetaType.Type: {ok_count}/{len(test_types)} доступны"
                )

        except ImportError:
            self.logger.warning("QMetaType недоступен")

        # --- NULL значение для QgsField ---
        try:
            from qgis.core import QgsField
            from qgis.PyQt.QtCore import QMetaType

            field = QgsField("test", QMetaType.Type.QString)
            self.logger.success(
                f"QgsField с QMetaType.Type.QString создан: {field.name()}"
            )
        except Exception as e:
            self.logger.warning(f"QgsField + QMetaType.Type: {e}")

    # ----------------------------------------------------------------
    # ТЕСТ 16: Runtime Processing algorithms
    # ----------------------------------------------------------------

    def test_16_runtime_processing_algorithms(self) -> None:
        """ТЕСТ 16: Доступность Processing алгоритмов, используемых плагином"""
        self.logger.section("16. Runtime: Processing algorithms")

        try:
            from qgis.core import QgsApplication

            registry = QgsApplication.processingRegistry()

            # Все алгоритмы, используемые плагином (из кодовой базы)
            plugin_algorithms = [
                ('native:fixgeometries', 'F_0_4 topology'),
                ('native:extractvertices', 'F_0_4 topology'),
                ('native:removeduplicatevertices', 'F_0_4 topology'),
                ('native:snapgeometries', 'F_0_4 topology'),
                ('native:buffer', 'F_1_1 import, M_41 isochrones'),
                ('native:polygonstolines', 'Fsm_1_2_8 geometry'),
                ('native:dissolve', 'processing ops'),
                ('native:intersection', 'processing ops'),
                ('native:difference', 'processing ops'),
                ('native:clip', 'processing ops'),
                ('native:simplifygeometries', 'M_41 results'),
                ('native:reprojectlayer', 'processing ops'),
                ('native:shortestpathpointtopoint', 'M_41 routes'),
                ('native:serviceareafrompoint', 'M_41 isochrones'),
                ('qgis:checkvalidity', 'F_0_4 topology'),
                ('gdal:contour_polygon', 'M_41 terrain'),
            ]

            ok_count = 0
            missing = []

            for alg_id, used_by in plugin_algorithms:
                alg = registry.algorithmById(alg_id)
                if alg:
                    ok_count += 1
                else:
                    missing.append((alg_id, used_by))

            if missing:
                self.logger.warning(
                    f"Processing: {ok_count}/{len(plugin_algorithms)} алгоритмов доступны"
                )
                for alg_id, used_by in missing:
                    self.logger.warning(f"  Отсутствует: {alg_id} ({used_by})")
                    self.issues.append({
                        'issue': f'Processing algorithm missing: {alg_id}',
                        'count': 1,
                        'severity': 'warning',
                    })
            else:
                self.logger.success(
                    f"Все {ok_count} Processing алгоритмов плагина доступны"
                )

        except Exception as e:
            self.logger.error(f"Ошибка проверки Processing: {e}")

    # ----------------------------------------------------------------
    # ТЕСТ 17: Third-party libraries
    # ----------------------------------------------------------------

    def test_17_runtime_third_party_libs(self) -> None:
        """ТЕСТ 17: Совместимость сторонних библиотек"""
        self.logger.section("17. Runtime: Third-party libraries")

        import sys
        self.logger.info(f"  Python {sys.version.split()[0]}")

        # --- ezdxf ---
        try:
            import ezdxf
            version = ezdxf.__version__
            doc = ezdxf.new('R2013')
            msp = doc.modelspace()
            self.logger.success(f"ezdxf {version}: new('R2013') + modelspace() OK")
        except ImportError:
            self.logger.warning("ezdxf не установлен")
        except Exception as e:
            self.logger.error(f"ezdxf ошибка: {e}")
            self.issues.append({
                'issue': f'ezdxf runtime error: {e}',
                'count': 1,
                'severity': 'error',
            })

        # --- xlsxwriter ---
        try:
            import xlsxwriter
            version = xlsxwriter.__version__
            import tempfile
            tmp = os.path.join(tempfile.gettempdir(), '_daman_qt6_test.xlsx')
            try:
                wb = xlsxwriter.Workbook(tmp)
                ws = wb.add_worksheet('test')
                ws.write(0, 0, 'Qt6 test')
                wb.close()
                self.logger.success(f"xlsxwriter {version}: Workbook + write OK")
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except ImportError:
            self.logger.warning("xlsxwriter не установлен")
        except Exception as e:
            self.logger.error(f"xlsxwriter ошибка: {e}")
            self.issues.append({
                'issue': f'xlsxwriter runtime error: {e}',
                'count': 1,
                'severity': 'error',
            })

        # --- requests ---
        try:
            import requests
            version = requests.__version__
            self.logger.success(f"requests {version}: import OK")
        except ImportError:
            self.logger.warning("requests не установлен")

        # --- lxml ---
        try:
            from lxml import etree
            version = etree.LXML_VERSION
            version_str = '.'.join(str(v) for v in version)
            root = etree.Element('test')
            etree.SubElement(root, 'child').text = 'value'
            xml_str = etree.tostring(root, encoding='unicode')
            self.logger.success(f"lxml {version_str}: Element + tostring OK")
        except ImportError:
            self.logger.warning("lxml не установлен")
        except Exception as e:
            self.logger.error(f"lxml ошибка: {e}")

        # --- openpyxl ---
        try:
            import openpyxl
            version = openpyxl.__version__
            self.logger.success(f"openpyxl {version}: import OK")
        except ImportError:
            self.logger.info("openpyxl не установлен (опционально)")

    # ----------------------------------------------------------------
    # ТЕСТ 12: Итоговая сводка
    # ----------------------------------------------------------------

    def test_12_summary(self) -> None:
        """ТЕСТ 12: Итоговая сводка"""
        self.logger.section("12. Итоговая сводка Qt6 совместимости")

        if not self.issues:
            self.logger.success("Плагин готов к Qt6/QGIS 4.0!")
            self.logger.info("  - Протестировать на QGIS Qt6 сборке")
            self.logger.info("  - Добавить supportsQt6=True в metadata.txt")
            return

        errors = [i for i in self.issues if i.get('severity') == 'error']
        warnings = [i for i in self.issues if i.get('severity') == 'warning']
        infos = [i for i in self.issues if i.get('severity') == 'info']

        error_count = sum(i.get('count', 1) for i in errors)
        warning_count = sum(i.get('count', 1) for i in warnings)
        info_count = sum(i.get('count', 1) for i in infos)
        total_count = error_count + warning_count + info_count

        self.logger.info("")
        self.logger.info(f"  Всего проблем: {total_count}")

        if errors:
            self.logger.error(f"  Критические: {error_count} ({len(errors)} категорий)")
        if warnings:
            self.logger.warning(f"  Предупреждения: {warning_count} ({len(warnings)} категорий)")
        if infos:
            self.logger.info(f"  Информационные: {info_count} ({len(infos)} категорий)")

        self.logger.info("")
        self.logger.info("  Приоритет исправлений (статический анализ):")
        self.logger.info("  1. exec_() -> exec() [механическая замена]")
        self.logger.info("  2. QVariant.* -> QMetaType.Type.* [критично]")
        self.logger.info("  3. Qt/Widget enum scoping [массовая замена]")
        self.logger.info("  4. QgsWkbTypes/QgsUnitTypes -> Qgis.* [QGIS 4.0]")
        self.logger.info("  5. Прямые импорты PyQt5 -> qgis.PyQt")
        self.logger.info("  6. QAction: QtWidgets -> QtGui")
        self.logger.info("")

        # Runtime issues
        runtime_issues = [
            i for i in self.issues
            if 'Runtime' in str(i.get('issue', ''))
            or 'runtime' in str(i.get('issue', ''))
            or 'Processing algorithm' in str(i.get('issue', ''))
        ]
        if runtime_issues:
            runtime_count = sum(i.get('count', 1) for i in runtime_issues)
            self.logger.warning(
                f"  Runtime проблемы: {runtime_count} "
                f"({len(runtime_issues)} категорий)"
            )
        else:
            self.logger.success("  Runtime проверки: все пройдены")
