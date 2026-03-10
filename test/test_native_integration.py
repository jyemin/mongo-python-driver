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

"""Integration tests for PyMongo API with native FFI backend.

These tests use the standard pymongo.MongoClient API and verify it works
correctly when delegating to the native FFI implementation.
"""

import unittest
from bson import ObjectId

from pymongo import MongoClient
from pymongo.native_bindings import is_available
from pymongo.native_bindings.sync_client import UnsupportedOperationError


class TestPyMongoNativeIntegration(unittest.TestCase):
    """Tests for PyMongo API with native FFI backend."""
    
    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        cls.client = MongoClient("localhost", 27017)
        # Verify native client is being used
        if cls.client._native_client is None:
            raise unittest.SkipTest("Native client not initialized")
        cls.db = cls.client["test_pymongo_native"]
        cls.coll = cls.db["test_collection"]
    
    @classmethod
    def tearDownClass(cls):
        cls.coll.drop()
        cls.client.close()
    
    def setUp(self):
        self.coll.drop()
    
    def test_native_client_initialized(self):
        """Verify MongoClient has native client."""
        self.assertIsNotNone(self.client._native_client)
    
    # -------------------------------------------------------------------------
    # Insert Operations
    # -------------------------------------------------------------------------
    
    def test_insert_one(self):
        """Test insert_one via PyMongo API."""
        result = self.coll.insert_one({"x": 1, "y": 2})
        self.assertIsInstance(result.inserted_id, ObjectId)
        self.assertTrue(result.acknowledged)
        
        # Verify document was inserted
        doc = self.coll.find_one({"x": 1})
        self.assertIsNotNone(doc)
        self.assertEqual(doc["y"], 2)
    
    def test_insert_one_with_custom_id(self):
        """Test insert_one with custom _id."""
        custom_id = ObjectId()
        result = self.coll.insert_one({"_id": custom_id, "x": 1})
        self.assertEqual(result.inserted_id, custom_id)
    
    def test_insert_many(self):
        """Test insert_many via PyMongo API."""
        docs = [{"x": i} for i in range(5)]
        result = self.coll.insert_many(docs)
        self.assertEqual(len(result.inserted_ids), 5)
        self.assertTrue(result.acknowledged)
        
        # Verify all documents were inserted
        count = len(list(self.coll.find()))
        self.assertEqual(count, 5)
    
    # -------------------------------------------------------------------------
    # Find Operations
    # -------------------------------------------------------------------------
    
    def test_find_one(self):
        """Test find_one via PyMongo API."""
        self.coll.insert_one({"name": "Alice", "age": 30})
        
        doc = self.coll.find_one({"name": "Alice"})
        self.assertIsNotNone(doc)
        self.assertEqual(doc["name"], "Alice")
        self.assertEqual(doc["age"], 30)
    
    def test_find_one_not_found(self):
        """Test find_one returns None when not found."""
        doc = self.coll.find_one({"name": "NonExistent"})
        self.assertIsNone(doc)
    
    def test_find_one_by_id(self):
        """Test find_one with ObjectId directly."""
        result = self.coll.insert_one({"x": 1})
        doc = self.coll.find_one(result.inserted_id)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["x"], 1)
    
    def test_find(self):
        """Test find via PyMongo API."""
        self.coll.insert_many([{"x": 1}, {"x": 2}, {"x": 3}])
        
        docs = list(self.coll.find())
        self.assertEqual(len(docs), 3)
    
    def test_find_with_filter(self):
        """Test find with filter."""
        self.coll.insert_many([{"x": 1}, {"x": 2}, {"x": 3}])
        
        docs = list(self.coll.find({"x": {"$gt": 1}}))
        self.assertEqual(len(docs), 2)
    
    def test_find_with_limit(self):
        """Test find with limit."""
        self.coll.insert_many([{"x": i} for i in range(10)])
        
        docs = list(self.coll.find(limit=3))
        self.assertEqual(len(docs), 3)
    
    def test_find_with_skip(self):
        """Test find with skip."""
        self.coll.insert_many([{"x": i} for i in range(10)])
        
        docs = list(self.coll.find(skip=7))
        self.assertEqual(len(docs), 3)
    
    def test_find_cursor_iteration(self):
        """Test cursor iteration with multiple batches."""
        self.coll.insert_many([{"i": i} for i in range(250)])
        
        count = 0
        for doc in self.coll.find(batch_size=10):
            count += 1
        self.assertEqual(count, 250)
    
    # -------------------------------------------------------------------------
    # Drop Operations
    # -------------------------------------------------------------------------
    
    def test_drop_collection(self):
        """Test drop via PyMongo API."""
        self.coll.insert_one({"x": 1})
        self.coll.drop()

        doc = self.coll.find_one()
        self.assertIsNone(doc)

    # -------------------------------------------------------------------------
    # Unsupported Operations
    # -------------------------------------------------------------------------

    def test_update_one_unsupported(self):
        """Test update_one raises UnsupportedOperationError."""
        self.coll.insert_one({"x": 1})
        with self.assertRaises(UnsupportedOperationError):
            self.coll.update_one({"x": 1}, {"$set": {"x": 2}})

    def test_update_many_unsupported(self):
        """Test update_many raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.update_many({}, {"$set": {"x": 2}})

    def test_delete_one_unsupported(self):
        """Test delete_one raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.delete_one({"x": 1})

    def test_delete_many_unsupported(self):
        """Test delete_many raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.delete_many({})

    def test_aggregate_unsupported(self):
        """Test aggregate raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.aggregate([{"$match": {"x": 1}}])

    def test_replace_one_unsupported(self):
        """Test replace_one raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.replace_one({"x": 1}, {"x": 2})

    def test_count_documents_unsupported(self):
        """Test count_documents raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.count_documents({})

    def test_distinct_unsupported(self):
        """Test distinct raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.distinct("field")

    def test_bulk_write_unsupported(self):
        """Test bulk_write raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.bulk_write([])

    def test_find_one_and_update_unsupported(self):
        """Test find_one_and_update raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.find_one_and_update({}, {"$set": {"x": 1}})

    def test_find_one_and_delete_unsupported(self):
        """Test find_one_and_delete raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.find_one_and_delete({})

    def test_create_index_unsupported(self):
        """Test create_index raises UnsupportedOperationError."""
        with self.assertRaises(UnsupportedOperationError):
            self.coll.create_index("field")

    # -------------------------------------------------------------------------
    # Database Operations
    # -------------------------------------------------------------------------

    def test_database_subscript_access(self):
        """Test database['collection'] access pattern."""
        coll = self.db["another_collection"]
        result = coll.insert_one({"test": True})
        self.assertIsNotNone(result.inserted_id)
        coll.drop()

    def test_client_subscript_access(self):
        """Test client['database']['collection'] access pattern."""
        coll = self.client["test_db"]["test_coll"]
        result = coll.insert_one({"test": True})
        self.assertIsNotNone(result.inserted_id)
        coll.drop()


class TestPyMongoNativeTransactions(unittest.TestCase):
    """Tests for PyMongo transactions with native FFI backend."""

    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        cls.client = MongoClient("localhost", 27017)
        if cls.client._native_client is None:
            raise unittest.SkipTest("Native client not initialized")

        # Check if replica set
        result = cls.client.admin.command("hello")
        if not result.get("setName"):
            cls.client.close()
            raise unittest.SkipTest("Transactions require a replica set")

        cls.db = cls.client["test_pymongo_native_txn"]
        cls.coll = cls.db["txn_test"]

    @classmethod
    def tearDownClass(cls):
        cls.coll.drop()
        cls.client.close()

    def setUp(self):
        self.coll.drop()

    def test_transaction_commit(self):
        """Test transaction commit via PyMongo API using native session."""
        # Use native client's session directly since PyMongo session
        # integration is not yet complete
        native_client = self.client._native_client
        native_coll = native_client[self.db.name][self.coll.name]

        with native_client.start_session() as session:
            session.start_transaction()
            native_coll.insert_one({"name": "Alice"}, session=session)
            native_coll.insert_one({"name": "Bob"}, session=session)
            session.commit_transaction()

        # Verify via PyMongo API
        docs = list(self.coll.find())
        self.assertEqual(len(docs), 2)

    def test_transaction_abort(self):
        """Test transaction abort via native session."""
        native_client = self.client._native_client
        native_coll = native_client[self.db.name][self.coll.name]

        native_coll.insert_one({"name": "Initial"})

        with native_client.start_session() as session:
            session.start_transaction()
            native_coll.insert_one({"name": "WillBeAborted"}, session=session)
            session.abort_transaction()

        # Verify via PyMongo API
        docs = list(self.coll.find())
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["name"], "Initial")


class TestAsyncPyMongoNativeIntegration(unittest.TestCase):
    """Tests for async PyMongo API with native FFI backend."""

    @classmethod
    def setUpClass(cls):
        if not is_available():
            raise unittest.SkipTest("Native library not available")
        import asyncio
        from pymongo import AsyncMongoClient
        cls.AsyncMongoClient = AsyncMongoClient
        cls.asyncio = asyncio

    def _run(self, coro):
        """Helper to run async code in sync tests."""
        return self.asyncio.get_event_loop().run_until_complete(coro)

    def test_native_client_initialized(self):
        """Verify AsyncMongoClient has native client."""
        async def run():
            async with self.AsyncMongoClient("localhost", 27017) as client:
                self.assertIsNotNone(client._native_client)
        self._run(run())

    def test_insert_one(self):
        """Test insert_one via async PyMongo API."""
        async def run():
            async with self.AsyncMongoClient("localhost", 27017) as client:
                coll = client["test_async_integration"]["test_coll"]
                await coll.drop()

                result = await coll.insert_one({"x": 1, "y": 2})
                self.assertIsInstance(result.inserted_id, ObjectId)

                doc = await coll.find_one({"x": 1})
                self.assertIsNotNone(doc)
                self.assertEqual(doc["y"], 2)

                await coll.drop()
        self._run(run())

    def test_insert_many(self):
        """Test insert_many via async PyMongo API."""
        async def run():
            async with self.AsyncMongoClient("localhost", 27017) as client:
                coll = client["test_async_integration"]["test_coll"]
                await coll.drop()

                result = await coll.insert_many([{"x": i} for i in range(5)])
                self.assertEqual(len(result.inserted_ids), 5)

                count = 0
                async for doc in coll.find():
                    count += 1
                self.assertEqual(count, 5)

                await coll.drop()
        self._run(run())

    def test_find_one(self):
        """Test find_one via async PyMongo API."""
        async def run():
            async with self.AsyncMongoClient("localhost", 27017) as client:
                coll = client["test_async_integration"]["test_coll"]
                await coll.drop()

                await coll.insert_one({"name": "Alice", "age": 30})
                doc = await coll.find_one({"name": "Alice"})
                self.assertIsNotNone(doc)
                self.assertEqual(doc["name"], "Alice")

                await coll.drop()
        self._run(run())

    def test_find_cursor_iteration(self):
        """Test cursor iteration with multiple batches."""
        async def run():
            async with self.AsyncMongoClient("localhost", 27017) as client:
                coll = client["test_async_integration"]["test_coll"]
                await coll.drop()

                await coll.insert_many([{"i": i} for i in range(250)])

                count = 0
                async for doc in coll.find(batch_size=10):
                    count += 1
                self.assertEqual(count, 250)

                await coll.drop()
        self._run(run())

    def test_unsupported_operations(self):
        """Test unsupported operations raise errors."""
        async def run():
            async with self.AsyncMongoClient("localhost", 27017) as client:
                coll = client["test_async_integration"]["test_coll"]

                with self.assertRaises(UnsupportedOperationError):
                    await coll.update_one({}, {"$set": {"x": 1}})

                with self.assertRaises(UnsupportedOperationError):
                    await coll.delete_one({})

                with self.assertRaises(UnsupportedOperationError):
                    await coll.aggregate([])
        self._run(run())


if __name__ == "__main__":
    unittest.main()

