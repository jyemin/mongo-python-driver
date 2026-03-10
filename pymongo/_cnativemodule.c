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
 */

#define PY_SSIZE_T_CLEAN
#include "Python.h"
#include <stdint.h>
#include <time.h>

/* Forward declarations for bson module functions */
static PyObject* _cbson_module = NULL;
static PyObject* _dict_to_bson_func = NULL;
static PyObject* _objectid_type = NULL;

/* Initialize references to bson module */
static int init_bson_refs(void) {
    if (_cbson_module != NULL) {
        return 0;  /* Already initialized */
    }
    
    _cbson_module = PyImport_ImportModule("bson._cbson");
    if (_cbson_module == NULL) {
        return -1;
    }
    
    _dict_to_bson_func = PyObject_GetAttrString(_cbson_module, "_dict_to_bson");
    if (_dict_to_bson_func == NULL) {
        return -1;
    }
    
    PyObject* bson_objectid = PyImport_ImportModule("bson.objectid");
    if (bson_objectid == NULL) {
        return -1;
    }
    _objectid_type = PyObject_GetAttrString(bson_objectid, "ObjectId");
    Py_DECREF(bson_objectid);
    if (_objectid_type == NULL) {
        return -1;
    }
    
    return 0;
}

/*
 * Prepare documents for insert_many.
 * 
 * Takes a sequence of documents, adds _id if not present, encodes to BSON.
 * Returns tuple of (list_of_bson_bytes, list_of_ids).
 */
static PyObject*
_cnative_prepare_insert_many(PyObject* self, PyObject* args) {
    PyObject* documents;
    PyObject* codec_options;
    
    if (!PyArg_ParseTuple(args, "OO", &documents, &codec_options)) {
        return NULL;
    }
    
    if (init_bson_refs() < 0) {
        return NULL;
    }
    
    /* Get iterator over documents */
    PyObject* iter = PyObject_GetIter(documents);
    if (iter == NULL) {
        return NULL;
    }
    
    /* Create result lists */
    PyObject* bson_list = PyList_New(0);
    PyObject* id_list = PyList_New(0);
    if (bson_list == NULL || id_list == NULL) {
        Py_XDECREF(bson_list);
        Py_XDECREF(id_list);
        Py_DECREF(iter);
        return NULL;
    }
    
    PyObject* doc;
    while ((doc = PyIter_Next(iter)) != NULL) {
        /* Make a copy of the dict */
        PyObject* doc_copy = PyDict_Copy(doc);
        Py_DECREF(doc);
        if (doc_copy == NULL) {
            goto error;
        }
        
        /* Check for _id, add if not present */
        PyObject* id_key = PyUnicode_FromString("_id");
        PyObject* existing_id = PyDict_GetItem(doc_copy, id_key);
        PyObject* doc_id;
        
        if (existing_id == NULL) {
            /* Generate new ObjectId */
            doc_id = PyObject_CallObject(_objectid_type, NULL);
            if (doc_id == NULL) {
                Py_DECREF(id_key);
                Py_DECREF(doc_copy);
                goto error;
            }
            if (PyDict_SetItem(doc_copy, id_key, doc_id) < 0) {
                Py_DECREF(id_key);
                Py_DECREF(doc_copy);
                Py_DECREF(doc_id);
                goto error;
            }
        } else {
            doc_id = existing_id;
            Py_INCREF(doc_id);
        }
        Py_DECREF(id_key);
        
        /* Encode to BSON using _cbson._dict_to_bson */
        PyObject* bson_args = PyTuple_Pack(3, doc_copy, Py_False, codec_options);
        Py_DECREF(doc_copy);
        if (bson_args == NULL) {
            Py_DECREF(doc_id);
            goto error;
        }
        
        PyObject* bson_bytes = PyObject_Call(_dict_to_bson_func, bson_args, NULL);
        Py_DECREF(bson_args);
        if (bson_bytes == NULL) {
            Py_DECREF(doc_id);
            goto error;
        }
        
        /* Append to result lists */
        if (PyList_Append(bson_list, bson_bytes) < 0 ||
            PyList_Append(id_list, doc_id) < 0) {
            Py_DECREF(bson_bytes);
            Py_DECREF(doc_id);
            goto error;
        }
        Py_DECREF(bson_bytes);
        Py_DECREF(doc_id);
    }
    
    Py_DECREF(iter);
    
    if (PyErr_Occurred()) {
        goto error;
    }
    
    /* Return tuple of (bson_list, id_list) */
    PyObject* result = PyTuple_Pack(2, bson_list, id_list);
    Py_DECREF(bson_list);
    Py_DECREF(id_list);
    return result;

error:
    Py_DECREF(iter);
    Py_DECREF(bson_list);
    Py_DECREF(id_list);
    return NULL;
}

/* Module method definitions */
static PyMethodDef _cnative_methods[] = {
    {"_prepare_insert_many", _cnative_prepare_insert_many, METH_VARARGS,
     "Prepare documents for insert_many.\n\n"
     "Takes a sequence of documents and codec_options.\n"
     "Returns tuple of (list_of_bson_bytes, list_of_ids)."},
    {NULL, NULL, 0, NULL}
};

/* Module definition */
static struct PyModuleDef _cnative_module = {
    PyModuleDef_HEAD_INIT,
    "_cnative",
    "C extension to accelerate native FFI operations.",
    -1,
    _cnative_methods,
    NULL,
    NULL,
    NULL,
    NULL
};

/* Module initialization */
PyMODINIT_FUNC
PyInit__cnative(void) {
    PyObject* module = PyModule_Create(&_cnative_module);
    if (module == NULL) {
        return NULL;
    }
    return module;
}

