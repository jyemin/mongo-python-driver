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

"""Error conversion from native FFI errors to PyMongo exceptions."""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from pymongo.errors import (
    AutoReconnect,
    BulkWriteError,
    ConfigurationError,
    ConnectionFailure,
    ExecutionTimeout,
    InvalidOperation,
    NetworkTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
    WriteError,
    WriteConcernError,
)

if TYPE_CHECKING:
    from pymongo.native_bindings._ffi import ffi

# Error type discriminators (from libmongodb.h)
_ERROR_TYPE_SERVER = 0
_ERROR_TYPE_INSERT_MANY = 1
_ERROR_TYPE_BULK_WRITE = 2
_ERROR_TYPE_IO = 3
_ERROR_TYPE_SERVER_SELECTION = 4
_ERROR_TYPE_TIMEOUT = 5
_ERROR_TYPE_AUTH = 6
_ERROR_TYPE_INVALID_ARGUMENT = 7
_ERROR_TYPE_TRANSACTION = 8
_ERROR_TYPE_INCOMPATIBLE_SERVER = 9
_ERROR_TYPE_INVALID_RESPONSE = 10
_ERROR_TYPE_CHANGE_STREAM = 11
_ERROR_TYPE_SHUTDOWN = 12


def _ffi_string(cdata) -> Optional[str]:
    """Convert a C string to Python string, or None if null."""
    from pymongo.native_bindings._ffi import ffi
    if cdata == ffi.NULL:
        return None
    return ffi.string(cdata).decode("utf-8")


def _extract_labels(labels_ptr, labels_len: int) -> List[str]:
    """Extract error labels from FFI array."""
    from pymongo.native_bindings._ffi import ffi
    if labels_ptr == ffi.NULL or labels_len == 0:
        return []
    return [ffi.string(labels_ptr[i]).decode("utf-8") for i in range(labels_len)]


def convert_error(error_ptr) -> PyMongoError:
    """Convert an FFI Error pointer to a PyMongo exception.
    
    Args:
        error_ptr: Pointer to an Error struct from the native library.
        
    Returns:
        A PyMongo exception corresponding to the error type.
    """
    from pymongo.native_bindings._ffi import ffi
    
    if error_ptr == ffi.NULL:
        return PyMongoError("Unknown error (null error pointer)")
    
    error_type = error_ptr.error_type
    error_union = error_ptr.error
    
    if error_type == _ERROR_TYPE_SERVER:
        err = error_union.server
        message = _ffi_string(err.message) or "Server error"
        code = err.code
        labels = _extract_labels(err.labels, err.labels_len)
        # OperationFailure expects error_labels in details dict
        details = {"errorLabels": labels} if labels else None
        return OperationFailure(message, code=code, details=details)
    
    elif error_type == _ERROR_TYPE_IO:
        err = error_union.io
        message = _ffi_string(err.message) or "I/O error"
        return AutoReconnect(message)
    
    elif error_type == _ERROR_TYPE_SERVER_SELECTION:
        err = error_union.server_selection
        message = _ffi_string(err.message) or "Server selection timeout"
        return ServerSelectionTimeoutError(message)
    
    elif error_type == _ERROR_TYPE_TIMEOUT:
        err = error_union.timeout
        message = _ffi_string(err.message) or "Operation timeout"
        return NetworkTimeout(message)
    
    elif error_type == _ERROR_TYPE_AUTH:
        err = error_union.auth
        message = _ffi_string(err.message) or "Authentication failed"
        return OperationFailure(message, code=18)  # AuthenticationFailed code
    
    elif error_type == _ERROR_TYPE_INVALID_ARGUMENT:
        err = error_union.invalid_argument
        message = _ffi_string(err.message) or "Invalid argument"
        return ConfigurationError(message)
    
    elif error_type == _ERROR_TYPE_TRANSACTION:
        err = error_union.transaction
        message = _ffi_string(err.message) or "Transaction error"
        labels = _extract_labels(err.labels, err.labels_len)
        details = {"errorLabels": labels} if labels else None
        return OperationFailure(message, details=details)
    
    elif error_type == _ERROR_TYPE_INCOMPATIBLE_SERVER:
        err = error_union.incompatible_server
        message = _ffi_string(err.message) or "Incompatible server"
        return ConfigurationError(message)
    
    elif error_type == _ERROR_TYPE_INVALID_RESPONSE:
        err = error_union.invalid_response
        message = _ffi_string(err.message) or "Invalid server response"
        return OperationFailure(message)
    
    elif error_type == _ERROR_TYPE_CHANGE_STREAM:
        err = error_union.change_stream
        message = _ffi_string(err.message) or "Change stream error"
        return OperationFailure(message)
    
    elif error_type == _ERROR_TYPE_SHUTDOWN:
        return InvalidOperation("Client has been closed")
    
    elif error_type == _ERROR_TYPE_INSERT_MANY:
        # TODO: Build proper BulkWriteError with write_errors
        return BulkWriteError({"writeErrors": [], "writeConcernErrors": []})
    
    elif error_type == _ERROR_TYPE_BULK_WRITE:
        # TODO: Build proper BulkWriteError with write_errors
        return BulkWriteError({"writeErrors": [], "writeConcernErrors": []})
    
    else:
        return PyMongoError(f"Unknown error type: {error_type}")

