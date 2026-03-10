# Python Driver Native FFI Integration Challenges

This document outlines the challenges, design decisions, and implementation plan for integrating the native core driver (`libmongocore`) into PyMongo via FFI.

## Overview

Following the same approach as the Java driver's `native-driver` branch, we will use FFI to delegate CRUD operations and connection management to the native core while keeping Python-specific concerns (codecs, API surface, type hints) in Python.

### Key Principle
**Native core handles**: Connection pooling, server selection, wire protocol, command execution, retries, batching, sessions, transactions
**Python handles**: BSON codecs, API surface, type hints, monitoring event dispatch, logging integration

### FFI Approach: `cffi`

For this prototype, we use `cffi` because:
- Cleaner API than `ctypes`
- Well-established in Python ecosystem (used by cryptography, PyNaCl, etc.)
- No compile tooling required at runtime (unlike PyO3)
- Supports both ABI mode (load .so/.dylib at runtime) and API mode (compile bindings)

Production may later consider `PyO3` for tighter integration, but `cffi` is ideal for prototyping.

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

### CHALLENGE-3: BSON Marshalling (MEDIUM)

**Problem**: Need to efficiently pass BSON documents between Python and native library.

**PyMongo BSON Types**:
- `bson.raw_bson.RawBSONDocument` - already raw bytes, zero-copy possible
- `dict` - needs encoding via `bson.encode()`
- Custom document classes via `CodecOptions`

**FFI Boundary**: Raw BSON bytes (`uint8_t*` + `size_t`)

**Solution**:
```python
class BsonMarshaller:
    def __init__(self, codec_options: CodecOptions):
        self.codec_options = codec_options

    def to_bytes(self, doc: Any) -> bytes:
        if isinstance(doc, RawBSONDocument):
            return bytes(doc.raw)
        return bson.encode(doc, codec_options=self.codec_options)

    def from_bytes(self, data: bytes) -> Any:
        if self.codec_options.document_class is RawBSONDocument:
            return RawBSONDocument(data)
        return bson.decode(data, codec_options=self.codec_options)
```

**Optimization**: For `RawBSONDocument`, we can pass pointer directly without copy.

**Status**: Straightforward, implementation pending

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

### CHALLENGE-10: Cursor Lifecycle (MEDIUM)

**Problem**: Cursors need to be properly closed, support iteration, getMore, etc.

**PyMongo Pattern**:
```python
cursor = collection.find({"x": 1})
for doc in cursor:
    print(doc)
# or
cursor.close()
```

**FFI Pattern**:
```python
class NativeCursor:
    def __init__(self, cursor_handle: ffi.CData, marshaller: BsonMarshaller):
        self._handle = cursor_handle
        self._marshaller = marshaller
        self._buffer: deque = deque()

    def __iter__(self):
        return self

    def __next__(self):
        if not self._buffer:
            self._fetch_batch()
        if not self._buffer:
            raise StopIteration
        return self._buffer.popleft()

    def _fetch_batch(self):
        result = lib.mongo_cursor_get_more(self._handle)
        for doc_bytes in iterate_batch(result):
            self._buffer.append(self._marshaller.from_bytes(doc_bytes))

    def close(self):
        lib.mongo_cursor_close(self._handle)
```

**Status**: Design complete

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
├── native_bindings/
│   ├── __init__.py
│   ├── _build.py              # cffi build script
│   ├── _ffi.py                # cffi definitions (from libmongodb.h)
│   ├── _loader.py             # Library loading logic
│   ├── _errors.py             # Error conversion
│   ├── _marshalling.py        # BSON and options marshalling
│   ├── _callbacks.py          # AsyncCallbackBridge, SyncCallbackBridge
│   ├── _client.py             # NativeClient (callback-based, sync/async agnostic)
│   ├── _cursor.py             # NativeCursor (callback-based)
│   └── _session.py            # NativeSession (callback-based)
```

Note: No `asynchronous/` and `synchronous/` subdirectories needed - the native bindings
are callback-based and sync/async agnostic. The sync/async distinction happens at the
integration level in `AsyncCollection`/`Collection` using the appropriate callback bridge.

## Open Questions

1. **Library Distribution**: Fat JAR equivalent for Python wheels? Platform-specific wheels?
2. **Fallback**: Should we fall back to pure-Python if native library unavailable?
3. **Feature Detection**: How to detect which features are supported by native library version?
4. **Testing**: How to test both native and pure-Python paths?

## References

- Java Driver `native-driver` branch: `../mongo-java-driver` (branch: `native-driver`)
- Native FFI layer: `../mongo-rust-driver` (branch: `ffi`)
- Java Integration Challenges: `../mongo-java-driver/JAVA_INTEGRATION_CHALLENGES.md` (branch: `core-rust-driver`)
- cffi documentation: https://cffi.readthedocs.io/

