"""Shared bases the concrete read adapters build on: ``PostgresReadAdapter``
(postgres.py, queried with SQL) and ``DynatraceReadAdapter`` (dynatrace.py, queried
with DQL). Not sources themselves - the four concrete read adapters in the parent
package subclass these.
"""
