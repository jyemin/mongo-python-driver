/*
 * Copyright 2024-present MongoDB, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * C extension to accelerate native FFI operations.
 * Links with _cbsonmodule.c to use internal BSON functions directly.
 */

#define PY_SSIZE_T_CLEAN
#include "Python.h"

#include "_cbsonmodule.h"
#include "buffer.h"

struct module_state {
    PyObject* _cbson;
};

#define GETSTATE(m) ((struct module_state*)PyModule_GetState(m))

/*
 * Encode documents to BSON bytes.
 * 
 * Takes a sequence of documents (with _ids already added) and codec_options.
 * Returns list of BSON bytes.
 * 
 * Uses write_dict directly from _cbson C API for maximum efficiency.
 */
static PyObject*
_cnative_encode_docs(PyObject* self, PyObject* args) {
    PyObject* documents;
    PyObject* codec_options_obj;
    struct module_state* state = GETSTATE(self);
    codec_options_t options;
    
    if (!PyArg_ParseTuple(args, "OO", &documents, &codec_options_obj)) {
        return NULL;
    }
    
    /* Convert codec options to C struct */
    if (!convert_codec_options(state->_cbson, codec_options_obj, &options)) {
        return NULL;
    }
    
    /* Get iterator over documents */
    PyObject* iter = PyObject_GetIter(documents);
    if (iter == NULL) {
        destroy_codec_options(&options);
        return NULL;
    }
    
    /* Create result list */
    PyObject* bson_list = PyList_New(0);
    if (bson_list == NULL) {
        Py_DECREF(iter);
        destroy_codec_options(&options);
        return NULL;
    }
    
    PyObject* doc;
    while ((doc = PyIter_Next(iter)) != NULL) {
        /* Allocate buffer for this document */
        buffer_t buffer = pymongo_buffer_new();
        if (buffer == NULL) {
            Py_DECREF(doc);
            PyErr_NoMemory();
            goto error;
        }
        
        /* Encode document directly using write_dict from _cbson C API */
        int size = write_dict(state->_cbson, buffer, doc, 0, &options, 1);
        Py_DECREF(doc);
        
        if (!size) {
            pymongo_buffer_free(buffer);
            goto error;
        }
        
        /* Convert buffer to Python bytes */
        PyObject* bson_bytes = PyBytes_FromStringAndSize(
            pymongo_buffer_get_buffer(buffer),
            (Py_ssize_t)pymongo_buffer_get_position(buffer));
        pymongo_buffer_free(buffer);
        
        if (bson_bytes == NULL) {
            goto error;
        }
        
        /* Append to result list */
        if (PyList_Append(bson_list, bson_bytes) < 0) {
            Py_DECREF(bson_bytes);
            goto error;
        }
        Py_DECREF(bson_bytes);
    }
    
    Py_DECREF(iter);
    destroy_codec_options(&options);
    
    if (PyErr_Occurred()) {
        Py_DECREF(bson_list);
        return NULL;
    }
    
    return bson_list;

error:
    Py_DECREF(iter);
    Py_DECREF(bson_list);
    destroy_codec_options(&options);
    return NULL;
}

/*
 * Decode BSON documents from an FFI BsonArray.
 *
 * Takes:
 *   - data_ptr: pointer to array of BSON document pointers (as int)
 *   - count: number of documents
 *   - codec_options: BSON codec options
 *
 * Returns list of decoded documents.
 */
static PyObject*
_cnative_decode_batch(PyObject* self, PyObject* args) {
    unsigned long long data_ptr_int;
    Py_ssize_t count;
    PyObject* codec_options_obj;
    struct module_state* state = GETSTATE(self);
    codec_options_t options;

    if (!PyArg_ParseTuple(args, "KnO", &data_ptr_int, &count, &codec_options_obj)) {
        return NULL;
    }

    const uint8_t *const *data_ptr = (const uint8_t *const *)data_ptr_int;

    /* Convert codec options to C struct */
    if (!convert_codec_options(state->_cbson, codec_options_obj, &options)) {
        return NULL;
    }

    /* Create result list with known size */
    PyObject* doc_list = PyList_New(count);
    if (doc_list == NULL) {
        destroy_codec_options(&options);
        return NULL;
    }

    for (Py_ssize_t i = 0; i < count; i++) {
        const char* doc_data = (const char*)data_ptr[i];

        /* BSON document length is first 4 bytes (little-endian) */
        uint32_t length = (uint32_t)doc_data[0] |
                          ((uint32_t)doc_data[1] << 8) |
                          ((uint32_t)doc_data[2] << 16) |
                          ((uint32_t)doc_data[3] << 24);

        /* Decode document directly using elements_to_dict */
        PyObject* doc = elements_to_dict(state->_cbson, doc_data, length, &options);
        if (doc == NULL) {
            Py_DECREF(doc_list);
            destroy_codec_options(&options);
            return NULL;
        }

        PyList_SET_ITEM(doc_list, i, doc);  /* Steals ref */
    }

    destroy_codec_options(&options);
    return doc_list;
}

/* Module methods */
static PyMethodDef _cnative_methods[] = {
    {"_encode_docs", _cnative_encode_docs, METH_VARARGS,
     "Encode documents to BSON bytes.\n\n"
     "Takes documents (with _ids) and codec_options.\n"
     "Returns list of BSON bytes."},
    {"_decode_batch", _cnative_decode_batch, METH_VARARGS,
     "Decode BSON documents from FFI BsonArray.\n\n"
     "Takes data_ptr (int), count, and codec_options.\n"
     "Returns list of decoded documents."},
    {NULL, NULL, 0, NULL}
};

static int _cnative_traverse(PyObject* m, visitproc visit, void* arg) {
    Py_VISIT(GETSTATE(m)->_cbson);
    return 0;
}

static int _cnative_clear(PyObject* m) {
    Py_CLEAR(GETSTATE(m)->_cbson);
    return 0;
}

/* Module definition */
static struct PyModuleDef _cnative_module = {
    PyModuleDef_HEAD_INIT,
    "_cnative",
    "C extension to accelerate native FFI operations.",
    sizeof(struct module_state),
    _cnative_methods,
    NULL,
    _cnative_traverse,
    _cnative_clear,
    NULL
};

/* Module initialization */
PyMODINIT_FUNC
PyInit__cnative(void) {
    PyObject* module = NULL;
    PyObject* _cbson = NULL;
    PyObject* c_api_object = NULL;
    struct module_state* state = NULL;

    module = PyModule_Create(&_cnative_module);
    if (module == NULL) {
        return NULL;
    }

    /* Import bson._cbson module */
    _cbson = PyImport_ImportModule("bson._cbson");
    if (_cbson == NULL) {
        goto fail;
    }

    /* Get the C API capsule */
    c_api_object = PyObject_GetAttrString(_cbson, "_C_API");
    if (c_api_object == NULL) {
        goto fail;
    }
    _cbson_API = (void **)PyCapsule_GetPointer(c_api_object, "_cbson._C_API");
    Py_DECREF(c_api_object);
    if (_cbson_API == NULL) {
        goto fail;
    }

    state = GETSTATE(module);
    state->_cbson = _cbson;

    return module;

fail:
    Py_XDECREF(_cbson);
    Py_DECREF(module);
    return NULL;
}

