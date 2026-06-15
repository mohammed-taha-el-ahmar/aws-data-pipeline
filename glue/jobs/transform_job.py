"""
Glue ETL job: transform

Runs on the Glue/Spark runtime (NOT a plain Python environment — this script
cannot be unit tested with a normal interpreter; the `awsglue` and `pyspark`
modules are only available inside a Glue job or the Glue Docker image).

Reads the "raw" table from the Glue Data Catalog (populated by the raw
crawler from s3://<bucket>/raw/), flattens it the same way as
shared/transform.py's `transform_record` — reimplemented here in Spark since
this job processes data in bulk rather than one record at a time — and
writes the result as Parquet to s3://<bucket>/processed/.

A second crawler (see terraform/main.tf) then catalogs processed/ so it can
be queried directly via Redshift Spectrum, without a separate load step.
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.functions import col

args = getResolvedOptions(
    sys.argv,
    ["JOB_NAME", "SOURCE_DATABASE", "SOURCE_TABLE", "TARGET_S3_PATH"],
)

sc = SparkContext()
glue_context = GlueContext(sc)
spark = glue_context.spark_session

job = Job(glue_context)
job.init(args["JOB_NAME"], args)

# Read the raw landed JSON via the Glue Data Catalog table created by the
# raw crawler (terraform/main.tf: aws_glue_crawler.raw).
raw_dyf = glue_context.create_dynamic_frame.from_catalog(
    database=args["SOURCE_DATABASE"],
    table_name=args["SOURCE_TABLE"],
)
raw_df = raw_dyf.toDF()

# Mirrors shared/transform.py: transform_record(). If you change the field
# mapping there, update this select() to match.
transformed_df = raw_df.select(
    col("ingested_at"),
    col("payload.latitude").alias("latitude"),
    col("payload.longitude").alias("longitude"),
    col("payload.current.temperature_2m").alias("temperature_c"),
    col("payload.current.wind_speed_10m").alias("wind_speed_kmh"),
    col("payload.current.relative_humidity_2m").alias("humidity_pct"),
)

# Write as Parquet, partitioned by the same date partitions the raw crawler
# picked up from the raw/year=/month=/day= layout (if present).
writer = transformed_df.write.mode("append").format("parquet")

partition_cols = [c for c in ("year", "month", "day") if c in transformed_df.columns]
if partition_cols:
    writer = writer.partitionBy(*partition_cols)

writer.save(args["TARGET_S3_PATH"])

job.commit()
