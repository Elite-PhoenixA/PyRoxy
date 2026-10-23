<<<<<<< HEAD
from pathlib import Path

from setuptools import setup

_HERE = Path(__file__).parent
_LONG_DESCRIPTION = (_HERE / "README.md").read_text(encoding="utf-8")

setup(
    name="PyRoxy",
    version="1.0b7",
    description="Proxy parsing, validation, checking, and GeoIP helpers",
    long_description=_LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    url="https://github.com/MHProDev/PyRoxy",
    license="MIT",
    license_files=["LICENSE.md"],
    author="MH_ProDev",
    python_requires=">=3.8",
    packages=[
        "PyRoxy", "PyRoxy.GeoIP", "PyRoxy.Tools", "PyRoxy.Exceptions"
    ],
    install_requires=[
        "maxminddb>=2.2.0",
        "requests>=2.27.1",
        "pysocks>=1.7.1",
    ],
    extras_require={
        "test": ["pytest>=7"],
    },
    include_package_data=True,
    package_data={
        "PyRoxy.GeoIP": ["Sqlite/*.txt", "Sqlite/GeoLite2-Country.mmdb"],
        "": ["LICENSE.md"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    project_urls={
        "Source": "https://github.com/MHProDev/PyRoxy",
        "Issues": "https://github.com/MHProDev/PyRoxy/issues",
    },
)
=======
from setuptools import setup

setup(name='PyRoxy',
      version="1.0b5",
      packages=['PyRoxy', 'PyRoxy.GeoIP', 'PyRoxy.Tools', 'PyRoxy.Exceptions'],
      url='https://github.com/MHProDev/PyRoxy',
      license='MIT',
      author="MH_ProDev",
      install_requires=[
          "maxminddb>=2.2.0", "requests>=2.27.1", "yarl>=1.7.2",
          "pysocks>=1.7.1"
      ],
      include_package_data=True,
      package_data={
          'PyRoxy.GeoIP': ['Sqlite/*.txt', "Sqlite/GeoLite2-Country.mmdb"],
          '': ["LICENSE.md"]
      })
>>>>>>> ea0f88dbc0573292ba5672124f69e4e7a31b544d
