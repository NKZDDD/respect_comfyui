from . import managed, managed_usage
from .apiutil import TASK_FATAL, ApiError


def event_id():
    event = managed_usage.snapshot()
    if not event:
        raise ApiError("转发缺少任务用量编号，请重新建立任务", kind=TASK_FATAL)
    return event["event_id"]


def call(owner, action, body):
    manager = managed.manager
    for attempt in range(2):
        with manager.lock:
            if not manager.tokens or owner != (manager.user or {}).get("id", manager._diagnostic_owner):
                raise managed.LoginRequired("请登录原账号使用转发")
            token = manager.tokens["access_token"]
            data = dict(body, device_id=manager.device_id())
        try:
            return manager.post("relay/" + action, data, token)
        except managed.LoginRequired as exc:
            if attempt or exc.code != "access_expired":
                raise
            with manager.lock:
                if manager.tokens and manager.tokens["access_token"] == token:
                    manager.verify()
