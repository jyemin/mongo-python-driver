# Copyright 2009-present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you
# may not use this file except in compliance with the License.  You
# may obtain a copy of the License at
#
# https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.  See the License for the specific language governing
# permissions and limitations under the License.

"""Minimal AsyncMongoClient that delegates to native FFI."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from bson.codec_options import CodecOptions, DEFAULT_CODEC_OPTIONS
from pymongo.asynchronous.database import AsyncDatabase

if TYPE_CHECKING:
    from pymongo.asynchronous.client_session import AsyncClientSession


class AsyncMongoClient:
    """Async client for MongoDB using native FFI.
    
    Only operations supported by native FFI are available.
    Unsupported operations raise NotImplementedError.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 27017,
        **kwargs: Any,
    ):
        from pymongo.native_bindings import NativeAsyncMongoClient

        # Parse host string
        if host is None:
            host = "localhost"

        # Handle mongodb:// URI
        if host.startswith("mongodb://") or host.startswith("mongodb+srv://"):
            uri = host
            if uri.startswith("mongodb://"):
                uri = uri[len("mongodb://"):]
            if "@" in uri:
                uri = uri.split("@")[1]
            if "/" in uri:
                uri = uri.split("/")[0]
            if "?" in uri:
                uri = uri.split("?")[0]
            host = uri

        self._native = NativeAsyncMongoClient(host, port, **kwargs)
        self._codec_options = DEFAULT_CODEC_OPTIONS

    async def close(self) -> None:
        """Close the client."""
        self._native.close()

    async def __aenter__(self) -> "AsyncMongoClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def __getitem__(self, name: str) -> AsyncDatabase:
        """Get a database by name."""
        return AsyncDatabase(self, name)

    def __getattr__(self, name: str) -> AsyncDatabase:
        """Get a database by attribute access."""
        if name.startswith("_"):
            raise AttributeError(f"AsyncMongoClient has no attribute {name!r}")
        return self[name]

    def get_database(
        self,
        name: str,
        codec_options: Optional[CodecOptions] = None,
    ) -> AsyncDatabase:
        """Get a database by name."""
        return AsyncDatabase(self, name, codec_options=codec_options or self._codec_options)

    @property
    def codec_options(self) -> CodecOptions:
        return self._codec_options

    def start_session(self, **kwargs: Any) -> "AsyncClientSession":
        """Start a client session."""
        from pymongo.asynchronous.client_session import AsyncClientSession, SessionOptions

        # Convert TransactionOptions to dict for FFI
        default_txn_opts = kwargs.get("default_transaction_options")
        txn_opts_dict = None
        if default_txn_opts:
            txn_opts_dict = {
                "read_concern": getattr(default_txn_opts, "read_concern", None),
                "write_concern": getattr(default_txn_opts, "write_concern", None),
                "read_preference": getattr(default_txn_opts, "read_preference", None),
                "max_commit_time_ms": getattr(default_txn_opts, "max_commit_time_ms", None),
            }

        native_session = self._native.start_session(
            causal_consistency=kwargs.get("causal_consistency", True),
            snapshot=kwargs.get("snapshot", False),
            default_transaction_options=txn_opts_dict,
        )
        options = SessionOptions(
            causal_consistency=kwargs.get("causal_consistency"),
            default_transaction_options=default_txn_opts,
            snapshot=kwargs.get("snapshot"),
        )
        return AsyncClientSession(self, native_session, options)

    async def drop_database(self, name: str, **kwargs: Any) -> None:
        """Drop a database."""
        await self._native[name].drop()

    async def server_info(self, **kwargs: Any) -> Any:
        """Get server information."""
        return await self._native["admin"].command("buildInfo")

    # Unsupported operations
    async def list_databases(self, **kwargs: Any) -> Any:
        raise NotImplementedError("list_databases not yet supported")

    async def list_database_names(self, **kwargs: Any) -> Any:
        raise NotImplementedError("list_database_names not yet supported")

    @property
    def address(self) -> Any:
        raise NotImplementedError("address not yet supported")

    @property
    def nodes(self) -> Any:
        raise NotImplementedError("nodes not yet supported")

    @property
    def options(self) -> Any:
        raise NotImplementedError("options not yet supported")

    @property
    def topology_description(self) -> Any:
        raise NotImplementedError("topology_description not yet supported")

