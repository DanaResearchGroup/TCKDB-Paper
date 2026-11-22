"""Create or drop an instance's database and bucket, run in the pinned TCKDB image by ``instance.py``.

    python -m snapshot.instance_admin create|drop

Reads ``DB_*`` and ``S3_*`` from the environment. ``create`` refuses an existing database; ``drop`` refuses a database
without the ``tckdb_test_`` prefix and empties the bucket before removing it.
"""

from __future__ import annotations

import os
import sys


def _connect():
    import psycopg

    return psycopg.connect(
        host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], dbname="postgres", autocommit=True,
    )


def _s3():
    import boto3

    return boto3.client(
        "s3", endpoint_url=os.environ["S3_ENDPOINT_URL"], aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"], region_name="us-east-1",
    )


def create() -> None:
    dbname = os.environ["DB_NAME"]
    with _connect() as conn:
        if conn.execute("select 1 from pg_database where datname = %s", (dbname,)).fetchone():
            raise SystemExit(f"database {dbname} already exists; run 'down --drop' first")
        conn.execute(f'create database "{dbname}"')
    _s3().create_bucket(Bucket=os.environ["S3_BUCKET"])


def drop() -> None:
    dbname = os.environ["DB_NAME"]
    if not dbname.startswith("tckdb_test_"):
        raise SystemExit(f"refusing to drop {dbname}: not a tckdb_test_* database")
    with _connect() as conn:
        conn.execute(f'drop database if exists "{dbname}" with (force)')
    client, bucket = _s3(), os.environ["S3_BUCKET"]
    try:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
        client.delete_bucket(Bucket=bucket)
    except client.exceptions.NoSuchBucket:
        pass


if __name__ == "__main__":
    {"create": create, "drop": drop}[sys.argv[1]]()
