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

"""Native bindings to libmongocore via cffi.

This module provides Python bindings to the native MongoDB driver core library,
which handles connection pooling, server selection, wire protocol, command
execution, retries, batching, sessions, and transactions.

The native bindings are callback-based and sync/async agnostic. The sync/async
distinction happens at the integration level using callback bridges:
- AsyncCallbackBridge: wraps callbacks in asyncio.Future
- SyncCallbackBridge: wraps callbacks in threading.Event
"""

from pymongo.native_bindings._loader import is_available, get_library_path
from pymongo.native_bindings._client import NativeClient
from pymongo.native_bindings._callbacks import AsyncCallbackBridge, SyncCallbackBridge

__all__ = [
    "is_available",
    "get_library_path",
    "NativeClient",
    "AsyncCallbackBridge",
    "SyncCallbackBridge",
]

