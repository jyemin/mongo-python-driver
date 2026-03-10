# Copyright 2017 MongoDB, Inc.
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

"""Minimal ClientSession that wraps native FFI session."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ContextManager, Optional

if TYPE_CHECKING:
    from pymongo.synchronous.mongo_client import MongoClient
    from pymongo.native_bindings.sync_client import NativeSyncSession


class SessionOptions:
    """Options for a ClientSession."""

    def __init__(
        self,
        causal_consistency: Optional[bool] = None,
        default_transaction_options: Optional["TransactionOptions"] = None,
        snapshot: Optional[bool] = False,
    ) -> None:
        self._causal_consistency = causal_consistency if causal_consistency is not None else True
        self._default_transaction_options = default_transaction_options
        self._snapshot = snapshot

    @property
    def causal_consistency(self) -> bool:
        return self._causal_consistency

    @property
    def default_transaction_options(self) -> Optional["TransactionOptions"]:
        return self._default_transaction_options

    @property
    def snapshot(self) -> Optional[bool]:
        return self._snapshot


class TransactionOptions:
    """Options for a transaction."""

    def __init__(
        self,
        read_concern: Optional[Any] = None,
        write_concern: Optional[Any] = None,
        read_preference: Optional[Any] = None,
        max_commit_time_ms: Optional[int] = None,
    ) -> None:
        self._read_concern = read_concern
        self._write_concern = write_concern
        self._read_preference = read_preference
        self._max_commit_time_ms = max_commit_time_ms

    @property
    def read_concern(self) -> Optional[Any]:
        return self._read_concern

    @property
    def write_concern(self) -> Optional[Any]:
        return self._write_concern

    @property
    def read_preference(self) -> Optional[Any]:
        return self._read_preference

    @property
    def max_commit_time_ms(self) -> Optional[int]:
        return self._max_commit_time_ms


class ClientSession:
    """Client session that wraps native FFI session.
    
    Supports transactions via start_transaction/commit_transaction/abort_transaction.
    """

    def __init__(
        self,
        client: "MongoClient",
        native_session: "NativeSyncSession",
        options: Optional[SessionOptions] = None,
    ) -> None:
        self._client = client
        self._native = native_session
        self._options = options or SessionOptions()

    def __enter__(self) -> "ClientSession":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.end_session()

    @property
    def client(self) -> "MongoClient":
        """The MongoClient this session was created from."""
        return self._client

    @property
    def options(self) -> SessionOptions:
        """The SessionOptions for this session."""
        return self._options

    @property
    def session_id(self) -> Any:
        """The session ID."""
        return self._native.session_id

    @property
    def has_ended(self) -> bool:
        """True if this session has been ended."""
        return self._native._handle is None

    @property
    def in_transaction(self) -> bool:
        """True if this session has an active transaction."""
        # TODO: track transaction state
        return False

    def end_session(self) -> None:
        """End this session."""
        self._native.end_session()

    def start_transaction(
        self,
        read_concern: Optional[Any] = None,
        write_concern: Optional[Any] = None,
        read_preference: Optional[Any] = None,
        max_commit_time_ms: Optional[int] = None,
    ) -> ContextManager["ClientSession"]:
        """Start a transaction."""
        # Only build options dict with non-None values
        options = {}
        if read_concern is not None:
            options["read_concern"] = read_concern
        if write_concern is not None:
            options["write_concern"] = write_concern
        if read_preference is not None:
            options["read_preference"] = read_preference
        if max_commit_time_ms is not None:
            options["max_commit_time_ms"] = max_commit_time_ms

        self._native.start_transaction(options if options else None)
        return _TransactionContext(self)

    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        self._native.commit_transaction()

    def abort_transaction(self) -> None:
        """Abort the current transaction."""
        self._native.abort_transaction()


class _TransactionContext:
    """Context manager for transactions."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    def __enter__(self) -> ClientSession:
        return self._session

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            self._session.commit_transaction()
        else:
            self._session.abort_transaction()

