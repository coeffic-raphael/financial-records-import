-- The image creates POSTGRES_DB and nothing else. The suite needs a second
-- database it is allowed to empty, and refuses to run against one whose name
-- does not end in _test.
CREATE DATABASE financial_records_test OWNER app;
