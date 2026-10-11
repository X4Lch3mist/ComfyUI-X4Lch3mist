"""
@author: X4Lch3mist
@title: X4Lch3mist Nodes
@nickname: X4Lch3mist
@description: Custom nodes by X4Lch3mist: Free Resolution Selector (freely configurable aspect ratio) and Load Checkpoint (Auto VAE/CLIP).
"""

import os
import importlib

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_base = os.path.dirname(__file__)

for _name in sorted(os.listdir(_base)):
    _path = os.path.join(_base, _name)
    if _name.startswith((".", "_")) or not os.path.isfile(os.path.join(_path, "__init__.py")):
        continue
    try:
        _mod = importlib.import_module(f".{_name}", __name__)
    except Exception as e:
        print(f"[X4Lch3mist] Failed to load {_name}: {e}")
        continue
    NODE_CLASS_MAPPINGS.update(getattr(_mod, "NODE_CLASS_MAPPINGS", {}))
    NODE_DISPLAY_NAME_MAPPINGS.update(getattr(_mod, "NODE_DISPLAY_NAME_MAPPINGS", {}))

WEB_DIRECTORY = "./web" if os.path.isdir(os.path.join(_base, "web")) else None

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
