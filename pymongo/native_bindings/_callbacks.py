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

"""Callback bridges for async and sync operation handling.

The native FFI is callback-based. These bridges convert callbacks to:
- AsyncCallbackBridge: asyncio.Future for async/await usage
- SyncCallbackBridge: threading.Event for blocking usage
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Optional, TypeVar, Generic

from pymongo.native_bindings._errors import convert_error
from pymongo.native_bindings._ffi import ffi

T = TypeVar("T")


class AsyncCallbackBridge(Generic[T]):
    """Bridge that converts FFI callbacks to asyncio Futures.

    Usage:
        bridge = AsyncCallbackBridge(result_converter)
        native_lib.some_operation(..., bridge.callback, bridge.handle)
        result = await bridge.future
    """

    def __init__(self, result_converter: Callable[[Any], T]):
        """Initialize the bridge.

        Args:
            result_converter: Function to convert the FFI result to Python type.
        """
        self._loop = asyncio.get_event_loop()
        self._future: asyncio.Future[T] = self._loop.create_future()
        self._result_converter = result_converter
        # Must keep a strong reference to prevent GC
        self._handle = ffi.new_handle(self)
        # Store references to FFI data that must stay alive until callback
        self._refs: list = []

    def keep_alive(self, *refs) -> "AsyncCallbackBridge[T]":
        """Keep references alive until the callback fires.

        Args:
            refs: Objects to keep alive (FFI buffers, structs, etc.)

        Returns:
            self for chaining
        """
        self._refs.extend(refs)
        return self
    
    @property
    def handle(self):
        """Get the FFI handle to pass as userdata."""
        return self._handle
    
    @property
    def future(self) -> asyncio.Future[T]:
        """Get the Future to await."""
        return self._future
    
    def _set_result(self, result: T) -> None:
        """Thread-safe result setter."""
        if not self._future.done():
            self._loop.call_soon_threadsafe(self._future.set_result, result)
    
    def _set_exception(self, exc: BaseException) -> None:
        """Thread-safe exception setter."""
        if not self._future.done():
            self._loop.call_soon_threadsafe(self._future.set_exception, exc)
    
    def on_complete(self, result_ptr, error_ptr) -> None:
        """Called by the FFI callback when operation completes.
        
        Args:
            result_ptr: Pointer to the result struct (or NULL on error).
            error_ptr: Pointer to the error struct (or NULL on success).
        """
        if error_ptr != ffi.NULL:
            exc = convert_error(error_ptr)
            self._set_exception(exc)
        else:
            try:
                result = self._result_converter(result_ptr)
                self._set_result(result)
            except Exception as e:
                self._set_exception(e)


class SyncCallbackBridge(Generic[T]):
    """Bridge that converts FFI callbacks to blocking waits.

    Usage:
        bridge = SyncCallbackBridge(result_converter)
        native_lib.some_operation(..., bridge.callback, bridge.handle)
        result = bridge.wait()
    """

    def __init__(self, result_converter: Callable[[Any], T]):
        """Initialize the bridge.

        Args:
            result_converter: Function to convert the FFI result to Python type.
        """
        self._event = threading.Event()
        self._result: Optional[T] = None
        self._error: Optional[BaseException] = None
        self._result_converter = result_converter
        # Must keep a strong reference to prevent GC
        self._handle = ffi.new_handle(self)
        # Store references to FFI data that must stay alive until callback
        self._refs: list = []

    def keep_alive(self, *refs) -> "SyncCallbackBridge[T]":
        """Keep references alive until the callback fires.

        Args:
            refs: Objects to keep alive (FFI buffers, structs, etc.)

        Returns:
            self for chaining
        """
        self._refs.extend(refs)
        return self
    
    @property
    def handle(self):
        """Get the FFI handle to pass as userdata."""
        return self._handle
    
    def wait(self, timeout: Optional[float] = None) -> T:
        """Block until the operation completes and return the result.
        
        Args:
            timeout: Maximum time to wait in seconds, or None for no timeout.
            
        Returns:
            The converted result.
            
        Raises:
            PyMongoError: If the operation failed.
            TimeoutError: If the wait timed out.
        """
        if not self._event.wait(timeout):
            raise TimeoutError("Operation timed out waiting for callback")
        
        if self._error is not None:
            raise self._error
        
        return self._result  # type: ignore
    
    def on_complete(self, result_ptr, error_ptr) -> None:
        """Called by the FFI callback when operation completes.
        
        Args:
            result_ptr: Pointer to the result struct (or NULL on error).
            error_ptr: Pointer to the error struct (or NULL on success).
        """
        if error_ptr != ffi.NULL:
            self._error = convert_error(error_ptr)
        else:
            try:
                self._result = self._result_converter(result_ptr)
            except Exception as e:
                self._error = e
        
        self._event.set()

