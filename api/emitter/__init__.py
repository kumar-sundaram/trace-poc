"""Emitter module: publishes outbound events to the two contract streams (FR-20).

Shared envelope, type-specific payloads: resolution-outcome (data consumers)
and signal (risk consumers), as append-only JSONL files in the POC — each
standing in for a broker topic. Streams are separated by data classification.
"""
