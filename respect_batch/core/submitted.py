"""Adapter submission hooks backed by Batch's account-scoped usage outbox.

The batch worker already owns attempt tracking. These hooks let Studio adapters
record their task IDs (including adapters with their own HTTP implementation)
without introducing a second ledger or automatically resubmitting pending work.
"""
from . import managed_usage


def submitting():
    event = managed_usage.snapshot()
    return managed_usage.active() and not (event or {}).get('task_id')


def remember(task_id, **resume):
    if task_id and managed_usage.active():
        if managed_usage.snapshot() is None:
            managed_usage.begin()
        managed_usage.note('submitted', task_id)


def discard():
    managed_usage.note('failed')
