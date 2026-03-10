# Copyright 2024-present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Library loader for libmongocore native library."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# Library names per platform
_LIB_NAMES = {
    "darwin": "libmongodb.dylib",
    "linux": "libmongodb.so",
    "win32": "mongodb.dll",
}

# Search paths for the native library
_SEARCH_PATHS = [
    # Environment variable override
    lambda: os.environ.get("LIBMONGODB_PATH"),
    # Adjacent to this module
    lambda: str(Path(__file__).parent / _get_lib_name()),
    # In pymongo package root
    lambda: str(Path(__file__).parent.parent / _get_lib_name()),
    # System library paths (Unix)
    lambda: f"/usr/local/lib/{_get_lib_name()}",
    lambda: f"/usr/lib/{_get_lib_name()}",
    # Homebrew on macOS
    lambda: f"/opt/homebrew/lib/{_get_lib_name()}",
    # Development: sibling mongo-rust-driver repo (release then debug)
    lambda: str(Path(__file__).resolve().parent.parent.parent.parent / "mongo-rust-driver" / "target" / "release" / _get_lib_name()),
    lambda: str(Path(__file__).resolve().parent.parent.parent.parent / "mongo-rust-driver" / "target" / "debug" / _get_lib_name()),
]

_lib_path: Optional[str] = None
_lib_available: Optional[bool] = None


def _get_lib_name() -> str:
    """Get the library filename for the current platform."""
    platform = sys.platform
    if platform.startswith("linux"):
        platform = "linux"
    return _LIB_NAMES.get(platform, "libmongocore.so")


def get_library_path() -> Optional[str]:
    """Find and return the path to the native library, or None if not found."""
    global _lib_path
    
    if _lib_path is not None:
        return _lib_path
    
    for path_fn in _SEARCH_PATHS:
        try:
            path = path_fn()
            if path and os.path.isfile(path):
                _lib_path = path
                return _lib_path
        except Exception:
            continue
    
    return None


def is_available() -> bool:
    """Check if the native library is available."""
    global _lib_available
    
    if _lib_available is not None:
        return _lib_available
    
    _lib_available = get_library_path() is not None
    return _lib_available

