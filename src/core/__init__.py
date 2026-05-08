"""
Shared building blocks for every feature in the Legal AI Hub.

Each feature module under `src/features/<name>/` is expected to import
helpers from this package rather than re-implementing them, so adding a
new feature stays small (~ pipeline.py + page.py).
"""
