import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="catt-cast-gui",
    version="0.1.0",
    author="ergosteur",
    description="A simple GUI for the 'cast to chromecast' (catt) command-line tool.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ergosteur/catt-cast-gui",  
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MPL-2.0 License",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Video",
        "Topic :: Multimedia :: Sound/Audio",
    ],
    python_requires='>=3.6',
    install_requires=[
        'PyQt5',
    ],
    entry_points={
        'console_scripts': [
            'catt-cast-gui = catt_cast_gui.gui:main',
            'piped-get-url = catt_cast_gui.piped:main_cli',
        ],
    },
)
