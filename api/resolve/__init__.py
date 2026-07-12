"""Resolve module: tiered matching pipeline and transactional graph writes.

Chain of responsibility (§5.2): Tier 1 exact SSN/Tax ID → Tier 2 normalized
name+address → Tier 3 vector similarity (same party type only) → Tier 4 LLM
disambiguation. Every resolution writes in a single ACID transaction (FR-7).
Fail toward review, never silent merge (§5.3).
"""
