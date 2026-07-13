"""Prompt templates for the LLM stages (extraction, clarification, suggestion).

Each structured-call template MUST carry the literal word "json" plus an example object
shape, or DeepSeek silently does not enter JSON mode and returns prose the Pydantic
contract cannot parse.
"""
