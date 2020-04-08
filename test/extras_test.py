"""
This tests extras_require feature of setuptools.

We declared isort[pyproject], which requires the toml module.
We wouldn't have that module otherwise.
"""

import toml
