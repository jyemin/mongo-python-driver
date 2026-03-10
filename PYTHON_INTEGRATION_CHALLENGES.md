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

### CHALLENGE-1: Sync/Async Integration (LOW - SOLVED)

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

**Status**: Design complete ✓

---

### CHALLENGE-2: Callback Bridges (HIGH)

**Problem**: Native FFI uses callback-based async (function pointer called when operation completes). Need to bridge to Python's async/await and blocking patterns.

**Native FFI Pattern**:
```c
void mongo_insert_one(
    MongoClient* client,
    const char* db,
    const char* coll,
    const uint8_t* doc_bytes,
    size_t doc_len,
    void (*callback)(void* context, MongoResult* result),
    void* context
);
```

**Solution - Two callback bridges**:
```python
# Async bridge - wraps callback in Future
class AsyncCallbackBridge:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.future: asyncio.Future = self.loop.create_future()

    def on_complete(self, result):
        if result.error:
            self.loop.call_soon_threadsafe(
                self.future.set_exception, convert_error(result.error))
        else:
            self.loop.call_soon_threadsafe(
                self.future.set_result, convert_result(result))

# Sync bridge - wraps callback in Event
class SyncCallbackBridge:
    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.error = None

    def on_complete(self, result):
        if result.error:
            self.error = convert_error(result.error)
        else:
            self.result = convert_result(result)
        self.event.set()

    def wait(self):
        self.event.wait()
        if self.error:
            raise self.error
        return self.result
```

**Usage in AsyncCollection**:
```python
async def insert_one(self, document, ...):
    bridge = AsyncCallbackBridge()
    self._native_client.insert_one(db, coll, doc_bytes, bridge.on_complete)
    return await bridge.future
```

**Usage in Collection**:
```python
def insert_one(self, document, ...):
    bridge = SyncCallbackBridge()
    self._native_client.insert_one(db, coll, doc_bytes, bridge.on_complete)
    return bridge.wait()
```

**Status**: Design complete

---

### CHALLENGE-3: BSON Marshalling (HIGH - SOLVED)

**Problem**: Efficiently pass BSON documents between Python and native library.

**FFI Boundary**: Raw BSON bytes (`uint8_t*` + `size_t`)

**Solution - C Extension `pymongo/_cnativemodule.c`**:

For **encoding** (insert_many), `_encode_docs()`:
- Takes a list of documents with `_id`s already added
- Calls `write_dict()` directly from the `_cbson` C API for each document
- Returns a list of BSON bytes

For **decoding** (find/cursor), `_decode_batch()`:
- Takes a pointer to the FFI's array of BSON document pointers and count
- Calls `elements_to_dict()` from the `_cbson` C API for each document
- Returns a list of decoded Python dicts

**Extended `_cbson` C API**: Added `elements_to_dict` to the C API capsule so `_cnative` can call it directly.

**Status**: Complete

---

### CHALLENGE-4: Event Listeners / Monitoring (HIGH)

**Problem**: PyMongo has extensive monitoring via `pymongo.monitoring`:
- `CommandListener` - command started/succeeded/failed
- `ServerListener` - server opened/closed/description changed
- `TopologyListener` - topology changes
- `ConnectionPoolListener` - pool events
- `ServerHeartbeatListener` - heartbeat events

**Current Pattern**: Events registered globally via `monitoring.register()` or per-client.

**FFI Requirement**: Native library needs to call back into Python when events occur.

**Solution** (similar to Java):
1. Register Python callbacks with native library at client creation
2. Native library calls `mongo_event_callback(event_type, event_data_bson)`
3. Python deserializes and dispatches to registered listeners

```python
@ffi.callback("void(int, const uint8_t*, size_t, void*)")
def _event_callback(event_type, data_ptr, data_len, context):
    client = ffi.from_handle(context)
    event_data = ffi.buffer(data_ptr, data_len)[:]
    event = deserialize_event(event_type, event_data)
    client._dispatch_event(event)
```

**Complexity**: Need to map native event types to PyMongo event classes.

**Status**: HIGH priority, requires native library support

---

### CHALLENGE-5: Logging Integration (HIGH)

**Problem**: PyMongo uses Python's `logging` module with specific loggers:
- `pymongo.command`
- `pymongo.connection`
- `pymongo.serverSelection`
- `pymongo.client`
- `pymongo.topology`

Native library uses `tracing` with a global subscriber.

**Solution Options**:
1. **Callback-based**: Native library calls Python for each log message (high overhead)
2. **Shared file/pipe**: Native library writes to a pipe, Python reads (complex)
3. **Disable native logging**: Only use event listeners (loses some debug info)

**Recommended**: Option 1 with filtering - only forward logs at DEBUG level or higher if Python logger is enabled at that level.

```python
@ffi.callback("void(int, const char*, void*)")
def _log_callback(level, message, context):
    logger = _level_to_logger(level)
    if logger.isEnabledFor(_rust_level_to_python(level)):
        logger.log(_rust_level_to_python(level), ffi.string(message).decode())
```

**Status**: Medium priority, can defer for prototype

---

### CHALLENGE-6: TLS/SSL Configuration (MEDIUM)

**Problem**: PyMongo supports:
- PEM certificate files (`tlsCertificateKeyFile`)
- CA files (`tlsCAFile`)
- CRL files (`tlsCRLFile`)
- PyOpenSSL for OCSP support

Native library uses its own TLS stack (rustls or native-tls).

**Supported by Native FFI**:
- PEM file paths (`tlsCertificateKeyFile`, `tlsCAFile`)
- Connection string TLS parameters (`tls`, `tlsAllowInvalidCertificates`, etc.)

**Needs Verification**:
- CRL files (`tlsCRLFile`) - need to verify native library support
- OCSP - native library may handle natively via rustls/webpki

**Solution**:
- Pass file paths directly to native library
- Most TLS configuration maps 1:1 to connection string parameters

**Status**: Mostly straightforward, verify CRL/OCSP support

---

### CHALLENGE-7: Authentication (HIGH)

**Handled Natively**:
- SCRAM-SHA-1, SCRAM-SHA-256
- MONGODB-X509
- PLAIN (LDAP)

**Requires Callbacks**:
- **MONGODB-AWS**: If using environment/EC2 metadata, native library handles it. Custom credential providers need callback.
- **MONGODB-OIDC**: Needs callback for token refresh

**Solution**: Similar to Java - register credential provider callbacks:
```python
@ffi.callback("void(CredentialRequest*, CredentialResponse*, void*)")
def _credential_callback(request, response, context):
    provider = ffi.from_handle(context)
    creds = provider.get_credentials()
    response.access_token = ffi.new("char[]", creds.access_token.encode())
    # etc.
```

**Status**: Design needed for OIDC callback interface

---

### CHALLENGE-8: Client-Side Field Level Encryption (HIGH)

**Problem**: PyMongo uses `pymongocrypt` (Python bindings to libmongocrypt).

**Why Python's pymongocrypt won't work**: Auto-encryption is deeply integrated into the command execution path:
1. Driver intercepts command
2. Consults encryption schema (requires server connection)
3. Encrypts fields via libmongocrypt
4. Sends encrypted command
5. Decrypts response

Since the native library now owns the entire command execution path (connections, retries, wire protocol), Python can't sit "outside" this loop and do encryption separately. The encryption must happen *inside* the native library.

**Solution**: Use the native library's built-in libmongocrypt integration. Configuration (key vault, KMS providers, schema maps) passed at client creation time.

**Explicit Encryption**: `ClientEncryption` for manual encrypt/decrypt operations may still use Python's pymongocrypt since it's not in the CRUD path.

**Status**: Requires native library CSFLE support; defer to Phase 2

---

### CHALLENGE-9: Sessions and Transactions (MEDIUM)

**Current PyMongo Pattern**:
```python
with client.start_session() as session:
    with session.start_transaction():
        coll.insert_one({"x": 1}, session=session)
        coll.update_one({"x": 1}, {"$set": {"y": 2}}, session=session)
```

**FFI Requirement**: Session handle from native library, passed to all operations.

**Solution**:
```python
class NativeClientSession:
    def __init__(self, session_handle: ffi.CData):
        self._handle = session_handle

    def start_transaction(self, **options):
        lib.mongo_session_start_transaction(self._handle, ...)

    def commit_transaction(self):
        lib.mongo_session_commit_transaction(self._handle, ...)

    def abort_transaction(self):
        lib.mongo_session_abort_transaction(self._handle, ...)
```

**Status**: Straightforward mapping to native FFI

---

### CHALLENGE-10: Cursor Lifecycle (MEDIUM - SOLVED)

**Problem**: Cursors need to be properly closed, support iteration, getMore, etc.

**Implementation**:
```python
class NativeSyncCursor:
    def __init__(self, native_client, cursor_handle, exhausted, first_batch, codec_options, session_handle=None):
        self._native = native_client
        self._cursor = cursor_handle
        self._exhausted = exhausted
        self._buffer = first_batch  # Use list directly from C extension
        self._index = 0
        self._codec_options = codec_options
        self._session = session_handle
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._index < len(self._buffer):
            doc = self._buffer[self._index]
            self._buffer[self._index] = None  # Allow GC
            self._index += 1
            return doc
        if self._exhausted or self._closed:
            raise StopIteration
        self._fetch_batch()
        if self._index < len(self._buffer):
            doc = self._buffer[self._index]
            self._buffer[self._index] = None
            self._index += 1
            return doc
        raise StopIteration

    def _fetch_batch(self):
        # Use C extension for batch decoding - pass FFI pointers directly
        def convert(result):
            exhausted, batch = result
            if batch.data == ffi.NULL or batch.len == 0:
                return exhausted, []
            data_ptr = cast_to_int(batch.data)
            docs = _decode_batch(data_ptr, batch.len, self._codec_options)
            return exhausted, docs

        bridge = SyncCallbackBridge(convert)
        self._native.cursor_get_more(self._cursor, callback, bridge.handle, session=self._session)
        self._exhausted, new_docs = bridge.wait()
        self._buffer = new_docs
        self._index = 0
```

**Key details**:
1. Use list with index instead of deque - avoids copying the decoded list
2. Null out elements after returning to allow GC
3. Use `_decode_batch` C extension to decode all docs in batch without Python loop
4. Cache `uintptr_t` type to avoid pycparser overhead on each pointer cast

**Status**: Complete

---

### CHALLENGE-11: Read/Write Concern and Read Preference (LOW)

**Problem**: Need to pass these settings to Rust FFI.

**Solution**: Marshal to FFI structs:
```python
def marshal_read_preference(rp: ReadPreference) -> ffi.CData:
    rp_struct = ffi.new("ReadPreference*")
    rp_struct.mode = rp.mode
    rp_struct.tag_sets = marshal_tag_sets(rp.tag_sets)
    rp_struct.max_staleness_seconds = rp.max_staleness
    return rp_struct
```

**Status**: Straightforward

---

### CHALLENGE-12: GridFS (LOW)

**Problem**: GridFS is built on top of collections.

**Solution**: If collections use native FFI, GridFS automatically benefits. No special handling needed.

**Status**: Automatic

---

### CHALLENGE-13: Change Streams (MEDIUM)

**Problem**: Long-running cursors that need to handle resume tokens, network errors, etc.

**Solution**: Similar to cursors, but with:
- Resume token tracking in Python
- Automatic resume on recoverable errors (handled by native library)

**Status**: Design needed

---

### CHALLENGE-14: Aggregation (LOW)

**Problem**: Aggregation pipelines are just BSON arrays.

**Solution**: Encode pipeline as BSON array, pass to `mongo_aggregate()`:
```python
def aggregate(self, pipeline: List[dict], **options):
    pipeline_bytes = bson.encode({"pipeline": pipeline})
    return NativeCursor(lib.mongo_aggregate(self._client, ..., pipeline_bytes, ...))
```

**Status**: Straightforward

---

## Implementation Plan

### Phase 1: Core Infrastructure
1. Set up `pymongo/native_bindings/` module structure
2. cffi build system integration (setup.py/pyproject.toml)
3. Library loading (`libmongocore.so/.dylib/.dll`)
4. Basic error conversion
5. BSON marshalling
6. Callback bridges (`AsyncCallbackBridge`, `SyncCallbackBridge`)

### Phase 2: Basic CRUD
1. `NativeClient` (callback-based, sync/async agnostic)
2. Basic cursor implementation (`NativeCursor`)
3. Integration with existing `AsyncCollection`/`Collection` using callback bridges
4. `insert_one`, `find_one`, `update_one`, `delete_one`

### Phase 3: Full CRUD + Sessions
1. All CRUD operations
2. Bulk writes
3. Sessions and transactions
4. Aggregation

### Phase 4: Advanced Features
1. Event listeners / monitoring
2. Change streams
3. Read/write concerns
4. Authentication callbacks (OIDC)

### Phase 5: Production Hardening
1. Error handling edge cases
2. Memory leak testing
3. Thread safety verification
4. Performance benchmarking
5. Documentation

## File Structure

```
pymongo/
├── _cnativemodule.c           # C extension for batch BSON encoding/decoding
├── native_bindings/
│   ├── __init__.py            # Exports NativeSyncMongoClient
│   ├── _ffi.py                # cffi definitions (from libmongodb.h), cast_to_int helper
│   ├── _loader.py             # Library loading logic (LIBMONGODB_PATH env var)
│   ├── _callbacks.py          # SyncCallbackBridge (threading.Event based)
│   ├── _client.py             # NativeClient (low-level FFI wrapper)
│   └── sync_client.py         # NativeSyncMongoClient, NativeSyncDatabase,
│                              # NativeSyncCollection, NativeSyncCursor
bson/
├── _cbsonmodule.c             # Extended C API with elements_to_dict
├── _cbsonmodule.h             # C API capsule definitions
```

**Integration Pattern**: `MongoClient` creates a `NativeSyncMongoClient` and delegates
CRUD operations to it. The native bindings use `SyncCallbackBridge` to convert
callback-based FFI to blocking Python calls.

## Performance Results

Benchmarks run with PyMongo's driver benchmark suite (7 tests matching Java driver-benchmarks):

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

