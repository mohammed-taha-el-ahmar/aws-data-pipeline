# Architecture

## Generic pattern

```mermaid
flowchart LR
    A[Source API] --> B[Ingest compute]
    B --> C[(Object storage - raw)]
    C --> D[Transform compute]
    D --> E[(Data warehouse)]
    E --> F[Dashboard / front end]
```

## AWS — Lambda + Glue + Redshift Spectrum

```mermaid
flowchart LR
    A[Open-Meteo API] -->|EventBridge hourly| B[Lambda: ingest]
    B --> C[(S3 raw/ - JSON)]
    C -->|Glue Crawler| D[(Glue Catalog: raw table)]
    D -->|Glue ETL Job - Spark| E[(S3 processed/ - Parquet)]
    E -->|Glue Crawler| F[(Glue Catalog: processed table)]
    F -->|Redshift Spectrum external schema| G[(Redshift Serverless)]
    G --> H[API Gateway]
    H --> I[Static front end]
```

The dotted line from raw crawl -> transform job -> processed crawl is a
single Glue Workflow (`aws_glue_workflow.pipeline`), chained with
`CONDITIONAL` triggers — Glue handles that orchestration natively, so Lambda
and Glue stay decoupled (Lambda doesn't need to know Glue exists, and vice
versa).
