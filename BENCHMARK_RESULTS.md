# Benchmark Results: Native FFI vs PyMongo

## Environment
- macOS (darwin)
- Python with C extensions enabled
- MongoDB standalone running locally with in memory storage engine
- Single-threaded benchmarks

## Results Summary

| Benchmark              | Native FFI   | PyMongo      | Difference |
|------------------------|--------------|--------------|------------|
| RunCommand             |   0.173 MB/s |   0.168 MB/s |     **+3%** |
| FindOneByID            |    16.6 MB/s |    14.0 MB/s |    **+19%** |
| SmallDocInsertOne      |    2.96 MB/s |    2.69 MB/s |    **+10%** |
| LargeDocInsertOne      |     320 MB/s |     380 MB/s |    **-16%** |
| FindManyAndEmptyCursor |     219 MB/s |     225 MB/s |     **-3%** |
| SmallDocBulkInsert     |     100 MB/s |     113 MB/s |    **-12%** |
| LargeDocBulkInsert     |     329 MB/s |     349 MB/s |     **-6%** |

## Raw Results

### Native FFI
```
TestRunCommand:           0.173 MB/s (MEDIAN=0.751s)
TestFindOneByID:          16.57 MB/s (MEDIAN=0.924s)
TestSmallDocInsertOne:    2.96 MB/s  (MEDIAN=0.844s)
TestLargeDocInsertOne:    320 MB/s   (MEDIAN=0.078s)
TestFindManyAndEmptyCursor: 219 MB/s (MEDIAN=0.070s)
TestSmallDocBulkInsert:   100 MB/s   (MEDIAN=0.025s)
TestLargeDocBulkInsert:   329 MB/s   (MEDIAN=0.076s)
```

### PyMongo (baseline)
```
TestRunCommand:           0.168 MB/s (MEDIAN=0.776s)
TestFindOneByID:          13.96 MB/s (MEDIAN=1.097s)
TestSmallDocInsertOne:    2.69 MB/s  (MEDIAN=0.930s)
TestLargeDocInsertOne:    380 MB/s   (MEDIAN=0.066s)
TestFindManyAndEmptyCursor: 225 MB/s (MEDIAN=0.068s)
TestSmallDocBulkInsert:   113 MB/s   (MEDIAN=0.022s)
TestLargeDocBulkInsert:   349 MB/s   (MEDIAN=0.072s)
```

