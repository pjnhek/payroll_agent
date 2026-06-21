"""Prompt templates for the judgment stages (extraction / reconcile / decide).

Each structured-call template MUST carry the literal word "json" plus an example
object shape, or DeepSeek silently does not enter JSON mode (RESEARCH Pitfall 1).
Phase 2 stages (Plan 02/03) fill this package in; Plan 01 only creates the seam.
"""
