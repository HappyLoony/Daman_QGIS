# Daman QGIS

![Version](https://img.shields.io/github/v/release/HappyLoony/Daman_QGIS)
![License](https://img.shields.io/badge/License-GPL--3.0-blue)
![QGIS](https://img.shields.io/badge/QGIS-3.40+-green)
![Python](https://img.shields.io/badge/Python-3.9+-yellow)

QGIS plugin for urban planning documentation (DPT - Documentation for Territory Planning) with support for Russian coordinate systems (MSK) and cadastral data formats.

## Features

- Import EGRN XML extracts (cadastral data)
- Topology validation
- Work with local coordinate systems (MSK)
- Export to CAD formats (DXF with HATCH, TAB)
- Preparation of cadastral registration materials
- Russian standards support: GOST 2.304, precision 0.01m

## Requirements

- QGIS 3.40 LTR or newer
- Python 3.9+

## Installation

### Via QGIS Plugin Manager (Recommended)

1. Open QGIS
2. Go to: Plugins > Manage and Install Plugins > Settings
3. Click "Add..." to add a new repository
4. Enter:
   - Name: `Daman QGIS (Stable)`
   - URL: `https://raw.githubusercontent.com/HappyLoony/Daman_QGIS/main/stable/plugins.xml`
5. Go to "All" tab and search for "Daman"
6. Install the plugin

### Beta Channel (for testers)

Use this URL instead:
```
https://raw.githubusercontent.com/HappyLoony/Daman_QGIS/main/beta/plugins.xml
```

## Author

Aleksandr Plakhotniuk
Email: sashaplahot@gmail.com

## License

GPL-3.0
