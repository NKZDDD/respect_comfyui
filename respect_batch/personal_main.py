"""自用版入口：保留全部适配器和设置，用独立数据目录保存 Key。"""
from core import paths

paths.APP_NAME = 'Respect-Batch-Personal'

import run
from core import server

server.PERSONAL = True

if __name__ == '__main__':
    raise SystemExit(run.main())
