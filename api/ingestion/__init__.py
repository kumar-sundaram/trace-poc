"""Ingestion module: receives source-tagged party events, validates (Pydantic), normalizes.

Write-path entry point (FR-1, FR-2, FR-8). Contract violations are rejected
synchronously with 4xx; accepted events are acknowledged 202 with a correlation
reference and handed to resolve.
"""
