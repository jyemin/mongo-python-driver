# Python Driver Native FFI Integration Challenges

This document outlines the challenges, design decisions, and implementation details for integrating a native core driver (`libmongodb`) into PyMongo via FFI.

## Overview

FFI delegates CRUD operations and connection management to the native core while keeping Python-specific concerns in Python.

### Responsibilities

**Native core handles**: Connection pooling, server selection, wire protocol, command execution, retries, batching, sessions, transactions

**Python handles**: BSON codecs (encoding/decoding), API surface, type hints, monitoring event dispatch, logging integration

### FFI Approach: `cffi`

`cffi` is used because:
- Cleaner API than `ctypes`
- Well-established in Python ecosystem (used by cryptography, PyNaCl, etc.)
- No compile tooling required at runtime (unlike PyO3)
- ABI mode allows loading pre-built native libraries without recompilation

## Architecture

The native FFI layer is **callback-based and sync/async agnostic**. There is a single `NativeClient` that takes callbacks. The sync/async distinction happens at the integration level in `AsyncCollection`/`Collection`, which use different callback bridges:
- **Async**: `AsyncCallbackBridge` wraps callbacks in `asyncio.Future`
- **Sync**: `SyncCallbackBridge` wraps callbacks in `threading.Event`

This means **no synchro.py changes are needed** for the native bindings module itself.

```
┌─────────────────────────────────────────────────────────────┐
│                     Python Application                       │
├─────────────────────────────────────────────────────────────┤
│  pymongo.asynchronous / pymongo.synchronous                 │
│  ┌─────────────────┐  ┌──────────────────┐                  │
│  │ AsyncMongoClient│  │   MongoClient    │                  │
│  │ AsyncCollection │  │   Collection     │                  │
│  │ AsyncCursor     │  │   Cursor         │                  │
│  └────────┬────────┘  └────────┬─────────┘                  │
│           │                    │                             │
│           │ AsyncCallbackBridge│ SyncCallbackBridge          │
│           │                    │                             │
│           ▼                    ▼                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              pymongo.native_bindings                    ││
│  │  ┌──────────────────────────────────────────┐           ││
│  │  │         NativeClient (callback-based)    │           ││
│  │  │  - insert_one(db, coll, doc, callback)   │           ││
│  │  │  - find(db, coll, filter, callback)      │           ││
│  │  │  - etc.                                  │           ││
│  │  └─────────────────────┬────────────────────┘           ││
│  │  ┌──────────────────────────────────────────┐           ││
│  │  │           Shared utilities               │           ││
│  │  │  - BsonMarshaller                        │           ││
│  │  │  - OptionsMarshaller                     │           ││
│  │  │  - ErrorConverter                        │           ││
│  │  └─────────────────────┬────────────────────┘           ││
│  └────────────────────────┼────────────────────────────────┘│
└───────────────────────────┼─────────────────────────────────┘
                            │ FFI (cffi)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    libmongocore.so/.dylib                   │
│  (Native driver with C FFI exports)                         │
│  - mongo_client_new()                                       │
│  - mongo_insert_one()                                       │
│  - mongo_find()                                             │
│  - mongo_cursor_get_more()                                  │
│  - etc.                                                     │
└─────────────────────────────────────────────────────────────┘
```

## Integration Challenges

### CHALLENGE-1: Sync/Async Integration (Implemented)

**Problem**: PyMongo uses `unasync` to generate synchronous code from async code. How does the native FFI layer work with both?

**Solution**: The native FFI is **callback-based and sync/async agnostic**.

The `NativeClient` class doesn't use `async/await` at all - it just takes a callback:
```python
native_client.insert_one(db, coll, doc_bytes, callback, context)
```

The sync/async distinction happens at the **integration level** in `AsyncCollection`/`Collection`:
- `AsyncCollection` uses `AsyncCallbackBridge` (wraps callback in `asyncio.Future`)
- `Collection` uses `SyncCallbackBridge` (wraps callback in `threading.Event`)

**No changes to synchro.py are needed** for the native bindings module.

---

### CHALLENGE-2: Callback Bridges (Implemented)

**Problem**: Native FFI uses callback-based async (function pointer called when operation completes). Need to bridge to Python's async/await and blocking patterns.

**Solution**: `SyncCallbackBridge` uses `threading.Event`, `AsyncCallbackBridge` uses `asyncio.Future` with `call_soon_threadsafe`.

---

### CHALLENGE-3: BSON Marshalling (Implemented)

**Problem**: Efficiently pass BSON documents between Python and native library.

**Solution**: C extension `pymongo/_cnativemodule.c` with:
- `_encode_docs_contiguous()`: Encodes docs to single buffer, returns buffer + pointer list
- `_decode_batch()`: Decodes from FFI pointer array using `_cbson` C API

Extended `_cbson` C API to expose `elements_to_dict`.

---

### CHALLENGE-4: Event Listeners / Monitoring

**Problem**: PyMongo has monitoring via `pymongo.monitoring` (CommandListener, ServerListener, etc).

**Solution**: Register Python callbacks with native library at client creation. Native library calls back with event data.

**Status**: Not implemented. Requires native library callback support.

---

### CHALLENGE-5: Logging Integration

**Problem**: PyMongo uses Python's `logging` module. Native library uses Rust `tracing`.

**Solution**: Callback-based forwarding with filtering.

**Status**: Not implemented.

---

### CHALLENGE-6: TLS/SSL Configuration

**Problem**: PyMongo supports TLS via PyOpenSSL. Native library uses rustls/native-tls.

**Solution**: Pass TLS file paths and options to native library via connection string.

**Status**: Implemented.

---

### CHALLENGE-7: Authentication

**Handled Natively**: SCRAM-SHA-1, SCRAM-SHA-256, MONGODB-X509, PLAIN (LDAP), MONGODB-AWS.

**Requires Callbacks**: MONGODB-OIDC needs callback for token refresh.

**Status**: Design complete for built-in auth. OIDC/AWS callbacks not implemented.

---

### CHALLENGE-8: Client-Side Field Level Encryption

**Problem**: Auto-encryption is integrated into the command execution path, which native library now owns.

**Solution**: Use native library's built-in libmongocrypt integration.

**Status**: Not implemented. Requires native library CSFLE support to pass auto-encryption options through

---

### CHALLENGE-9: Sessions and Transactions 

**Problem**: Sessions and transactions need to pass session handle to all operations.

**Solution**: `ClientSession` wraps `NativeSyncSession`. Session handle passed to FFI operations.
`SessionOptions` and `TransactionOptions` fully wired up.

**Status**: Implemented.

---

### CHALLENGE-10: Cursor Lifecycle

**Problem**: Cursors need proper iteration, getMore, and cleanup.

**Solution**: `NativeSyncCursor` with list+index pattern (not deque) for GC-friendly iteration.
Uses `_decode_batch` C extension for batch decoding.

**Status**: Implemented.

## File Structure

```
pymongo/
├── _cnativemodule.c              # C extension for batch BSON encoding/decoding
├── native_bindings/
│   ├── __init__.py               # Exports NativeSyncMongoClient, NativeAsyncMongoClient
│   ├── _ffi.py                   # cffi definitions, cast_to_int helper
│   ├── _loader.py                # Library loading (LIBMONGODB_PATH env var)
│   ├── _callbacks.py             # SyncCallbackBridge, AsyncCallbackBridge
│   ├── _client.py                # NativeClient (low-level FFI wrapper)
│   ├── sync_client.py            # NativeSyncMongoClient, NativeSyncSession, etc.
│   └── async_client.py           # NativeAsyncMongoClient, NativeAsyncSession, etc.
├── synchronous/
│   ├── mongo_client.py           # Thin wrapper delegating to native
│   ├── database.py               # Thin wrapper delegating to native
│   ├── collection.py             # Thin wrapper delegating to native
│   └── client_session.py         # ClientSession wrapping NativeSyncSession
├── asynchronous/
│   ├── mongo_client.py           # Async wrapper delegating to native
│   ├── database.py               # Async wrapper delegating to native
│   ├── collection.py             # Async wrapper delegating to native
│   └── client_session.py         # AsyncClientSession wrapping NativeAsyncSession
bson/
├── _cbsonmodule.c                # Extended C API with elements_to_dict
├── _cbsonmodule.h                # C API capsule definitions
```

**Integration Pattern**: `MongoClient` and `AsyncMongoClient` are thin wrappers that
delegate to native bindings. All SDAM, connection pooling, and wire protocol is handled
by the native library.

## Performance Results

Benchmarks run with PyMongo's driver benchmark suite:

```
Benchmark              PyMongo   Native    Rust     vs PyMongo
---------------------  --------  -------   ------   ----------
Run command               0.17     0.17     0.20        0% ≈
Find one                 13.59    13.45    20.18       -1% ≈
Small doc insertOne       2.63     2.69     4.02       +2% ≈
Large doc insertOne        375      390      569       +4% ≈
Find many (cursor)         224      225      229        0% ≈
Small doc bulk insert      113      114      175        0% ≈
Large doc bulk insert      341      344      520        0% ≈
```

**Performance observations**:

1. **C extensions for batch operations**: Initial implementation showed slower bulk insert and cursor iteration. The per-document Python function call overhead was the bottleneck, not FFI. Moving encoding/decoding loops into C resolved this.

2. **Reuse existing C infrastructure**: PyMongo's `_cbson` has optimized `write_dict` and `elements_to_dict` functions. Extending the C API to expose these was more effective than reimplementing.

3. **Avoid Python loops for batches**: Pass FFI pointer arrays directly to C extensions rather than iterating in Python.

4. **Cursor buffer**: Use list with index and null-out pattern instead of deque. Avoids copying the decoded list while still allowing GC of processed documents.

5. **Cache cffi types**: `ffi.cast("uintptr_t", ptr)` parses the type string each time. Caching with `ffi.typeof()` avoids pycparser overhead.

## Open Questions

1. **Library Distribution**: Platform-specific wheels with bundled native library?
2. **Fallback**: Should the driver fall back to pure-Python if native library unavailable?
3. **Feature Detection**: How to detect which features are supported by native library version?
4. **Testing**: How to test both native and pure-Python paths?

## References

- cffi documentation: https://cffi.readthedocs.io/

