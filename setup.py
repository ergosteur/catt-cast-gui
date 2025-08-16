#!/usr/bin/env python3
import setuptools
from pathlib import Path

README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")

setuptools.setup(
    name="catt-cast-gui",
    version="0.1.0",
    author="ergosteur",
    description="A simple GUI for the 'cast to chromecast' (catt) command-line tool.",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/ergosteur/catt-cast-gui",
    project_urls={
        "Bug Tracker": "https://github.com/ergosteur/catt-cast-gui/issues",
        "Source": "https://github.com/ergosteur/catt-cast-gui",
    },
    license="MPL-2.0",
    license_files=["LICENSE"],
    packages=setuptools.find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Video",
        "Topic :: Multimedia :: Sound/Audio",
    ],
    python_requires=">=3.8",
    install_requires=[
        "PyQt5",
        "catt>=0.10.0",  # Ensure catt is installed, version >= 0.10.0]
    ],
    entry_points={
        "console_scripts": [
            "catt-cast-gui = catt_cast_gui.gui:main",
            "piped-get-url = catt_cast_gui.piped:main_cli"
        ],
    },
)
