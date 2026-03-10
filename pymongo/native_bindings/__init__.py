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

"""Native bindings to libmongodb via cffi.

This module provides Python bindings to the native MongoDB driver core library,
which handles connection pooling, server selection, wire protocol, command
execution, retries, batching, sessions, and transactions.

High-level API:
- NativeSyncMongoClient: Synchronous MongoDB client
- NativeAsyncMongoClient: Asynchronous MongoDB client

Low-level API:
- NativeClient: Callback-based client (sync/async agnostic)
- AsyncCallbackBridge: Wraps callbacks in asyncio.Future
- SyncCallbackBridge: Wraps callbacks in threading.Event
"""

from pymongo.native_bindings._loader import is_available, get_library_path
from pymongo.native_bindings._client import NativeClient
from pymongo.native_bindings._callbacks import AsyncCallbackBridge, SyncCallbackBridge
from pymongo.native_bindings.sync_client import (
    NativeSyncMongoClient,
    NativeSyncDatabase,
    NativeSyncCollection,
    NativeSyncCursor,
    UnsupportedOperationError,
)
from pymongo.native_bindings.async_client import (
    NativeAsyncMongoClient,
    NativeAsyncDatabase,
    NativeAsyncCollection,
    NativeAsyncCursor,
)

__all__ = [
    # High-level API
    "NativeSyncMongoClient",
    "NativeSyncDatabase",
    "NativeSyncCollection",
    "NativeSyncCursor",
    "NativeAsyncMongoClient",
    "NativeAsyncDatabase",
    "NativeAsyncCollection",
    "NativeAsyncCursor",
    "UnsupportedOperationError",
    # Low-level API
    "is_available",
    "get_library_path",
    "NativeClient",
    "AsyncCallbackBridge",
    "SyncCallbackBridge",
]

