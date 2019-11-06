#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Note: To use the 'upload' functionality of this file, you must:
#   $ pip install twine

import io
import os
import sys
import time
from shutil import rmtree

from setuptools import find_packages, setup, Command

# Package meta-data.
NAME = 'websocks'
DESCRIPTION = 'A websocket-based socks5 proxy.'
URL = 'https://github.com/abersheeran/websocks'
EMAIL = 'me@abersheeran.com'
AUTHOR = 'Aber Sheeran'
REQUIRES_PYTHON = '>=3.6.0'
VERSION = "0.1.0"

# What packages are required for this module to be executed?
REQUIRED = [
    "uvloop==0.13.0 ; sys_platform != 'win32' and sys_platform != 'cygwin' and platform_python_implementation != 'pypy'",
    "websockets==8.0.2",
    "click"
]

# What packages are optional?
EXTRAS = {
    # 'fancy feature': ['django'],
}

# The rest you shouldn't have to touch too much :)
# ------------------------------------------------
# Except, perhaps the License and Trove Classifiers!
# If you do change the License, remember to change the Trove Classifier for that!

here = os.path.abspath(os.path.dirname(__file__))

# Import the README and use it as the long-description.
# Note: this will only work if 'README.md' is present in your MANIFEST.in file!
try:
    with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
        long_description = '\n' + f.read()
except FileNotFoundError:
    long_description = DESCRIPTION


class UploadCommand(Command):
    """Support setup.py upload."""

    description = 'Build and publish the package.'
    user_options = []

    @staticmethod
    def status(s):
        """Prints things in bold."""
        print('\033[1m{0}\033[0m'.format(s), flush=True)

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.status('Removing previous builds…')
        rmtree(os.path.join(here, 'build'), ignore_errors=True)
        rmtree(os.path.join(here, 'dist'), ignore_errors=True)

        self.status('Building Source and Wheel (universal) distribution…')
        os.system('{0} setup.py sdist bdist_wheel --universal'.format(sys.executable))

        self.status('Uploading the package to PyPI via Twine…')
        os.system('twine upload dist/*')

        self.status('Pushing git tags…')
        os.system('git tag v{0}'.format(VERSION))
        os.system('git push --tags')

        sys.exit()


# Where the magic happens:
setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type='text/markdown',
    author=AUTHOR,
    author_email=EMAIL,
    python_requires=REQUIRES_PYTHON,
    url=URL,
    packages=find_packages(include=["websocks"]),
    entry_points={
        'console_scripts': ['websocks=websocks.commands:main'],
    },
    install_requires=REQUIRED,
    extras_require=EXTRAS,
    include_package_data=True,
    license="Apache 2.0",
    classifiers=[
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
    # $ setup.py publish support.
    cmdclass={
        'upload': UploadCommand,
    },
)
