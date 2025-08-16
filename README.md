# catt-cast-gui

A simple PyQt5 GUI for [catt (Cast All The Things)](https://github.com/skorokithakis/catt).

This application provides a straightforward graphical user interface to discover and cast media to Chromecast devices on your local network. It is inspired by [catt-qt](https://github.com/soreau/catt-qt).

## Screenshot

*(A screenshot of the application in action would be great here!)*

## Features

*   **Scan for Devices**: Automatically scan and list available Chromecast devices.
*   **Cast Media**: Cast any direct video URL to a selected device.
*   **Playback Control**: Basic controls like play, pause, and stop.
*   **URL Helper**: Includes a helper script (`piped-get-url`) to resolve streamable URLs from services like Piped (a privacy-friendly YouTube frontend).

## Requirements

*   Python 3.6+
*   `catt`
*   `PyQt5`

The installer will handle these Python dependencies automatically.

## Installation

### From PyPI

The easiest way to install is via `pipx`:

```bash
pipx install git+https://github.com/ergosteur/catt-cast-gui.git
```

### From Source

```bash
git clone https://github.com/ergosteur/catt-cast-gui.git
cd catt-cast-gui
pip install .
```

## Usage

Once installed, simply run the following command in your terminal to launch the GUI:

```bash
catt-cast-gui
```

The Piped helper script can also be called directly via cli:
```bash
piped-get-url
``` 

## License

This project is distributed under the Mozilla Public License 2.0.


## Acknowledgements

*   This project was inspired by catt-qt.
*   This GUI would be nothing without the underlying power of catt and pychromecast.
