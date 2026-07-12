"""测试进程的非生产配置，必须在导入应用模块前设置。"""

import os


os.environ.setdefault("JWT_SECRET", "test-only-signing-key-not-for-deployment")
os.environ.setdefault("SEED_DEMO_PASSWORD", "test-runtime-password")
