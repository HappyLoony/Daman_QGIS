# Daman QGIS

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

## Documentation

See `documentation/` folder for detailed guides (in Russian).

## Author

Alexander Plahotnyuk
Email: sashaplahot@gmail.com

## License

GPL-3.0
