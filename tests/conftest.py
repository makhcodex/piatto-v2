"""Root test configuration.

Deliberately empty of database machinery. Anything requiring a driver, an event
loop, or a connection belongs in tests/services/conftest.py — `pytest tests/domain`
must stay runnable with nothing but pytest installed.
"""
