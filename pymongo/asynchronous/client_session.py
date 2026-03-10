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

"""Minimal AsyncClientSession that wraps native FFI session."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncContextManager, Optional

if TYPE_CHECKING:
    from pymongo.asynchronous.mongo_client import AsyncMongoClient
    from pymongo.native_bindings.async_client import NativeAsyncSession


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


class AsyncClientSession:
    """Async client session that wraps native FFI session."""

    def __init__(
        self,
        client: "AsyncMongoClient",
        native_session: "NativeAsyncSession",
        options: Optional[SessionOptions] = None,
    ) -> None:
        self._client = client
        self._native = native_session
        self._options = options or SessionOptions()

    async def __aenter__(self) -> "AsyncClientSession":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.end_session()

    @property
    def client(self) -> "AsyncMongoClient":
        return self._client

    @property
    def options(self) -> SessionOptions:
        return self._options

    @property
    def session_id(self) -> Any:
        return self._native.session_id

    @property
    def has_ended(self) -> bool:
        return self._native._handle is None

    @property
    def in_transaction(self) -> bool:
        return False

    async def end_session(self) -> None:
        self._native.end_session()

    def start_transaction(
        self,
        read_concern: Optional[Any] = None,
        write_concern: Optional[Any] = None,
        read_preference: Optional[Any] = None,
        max_commit_time_ms: Optional[int] = None,
    ) -> AsyncContextManager["AsyncClientSession"]:
        """Start a transaction."""
        options = {}
        if read_concern is not None:
            options["read_concern"] = read_concern
        if write_concern is not None:
            options["write_concern"] = write_concern
        if read_preference is not None:
            options["read_preference"] = read_preference
        if max_commit_time_ms is not None:
            options["max_commit_time_ms"] = max_commit_time_ms
        return _AsyncTransactionContext(self, options if options else None)

    async def commit_transaction(self) -> None:
        await self._native.commit_transaction()

    async def abort_transaction(self) -> None:
        await self._native.abort_transaction()


class _AsyncTransactionContext:
    """Async context manager for transactions."""

    def __init__(self, session: AsyncClientSession, options: Optional[dict]) -> None:
        self._session = session
        self._options = options

    async def __aenter__(self) -> AsyncClientSession:
        await self._session._native.start_transaction(self._options)
        return self._session

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            await self._session.commit_transaction()
        else:
            await self._session.abort_transaction()

