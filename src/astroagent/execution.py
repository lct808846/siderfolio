"""新会话与旧聊天共同使用的进程内模型任务上限。"""

import threading

MODEL_TASK_SLOTS = threading.BoundedSemaphore(2)
