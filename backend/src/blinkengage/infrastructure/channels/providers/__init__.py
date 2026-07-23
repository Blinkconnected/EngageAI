"""Import every concrete ``ChannelProvider`` module here so
``@ChannelRegistry.register(...)`` runs at import time — mirrors
``core/celery_app.py``'s own ``include=[...]`` task-discovery pattern.

Empty until the first real provider lands (Web Chat, M12) — M11 (this
milestone) proves the registry/factory/webhook-ingress architecture with a
test-only provider registered directly in its test module, per the
explicit requirement that provider implementations wait until the
architecture itself is signed off.
"""
