"""
Bootstrap PYTHONPATH for Agent.API → Agent.Core imports.

This module ensures `from core.xxx import ...`, `from tools.xxx import ...`,
`from agents.xxx import ...` etc. work whether running locally (sibling dirs)
or on the server (core/ deployed inside api/).

Usage:
    import path_setup  # noqa: F401  (must be first import)
"""
import os
import sys

_api_dir = os.path.dirname(os.path.abspath(__file__))

if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

_core_dir = os.path.join(_api_dir, 'core')
if not os.path.isdir(os.path.join(_core_dir, 'core')):
    _core_dir = os.path.abspath(os.path.join(_api_dir, '..', 'agent.core'))
    if not os.path.isdir(_core_dir):
        _core_dir = os.path.abspath(os.path.join(_api_dir, '..', 'Agent.Core'))

if _core_dir not in sys.path:
    sys.path.insert(0, _core_dir)
