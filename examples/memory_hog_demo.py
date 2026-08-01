"""Simulates a job that uses more memory than declared."""

import time

data = bytearray(500 * 1024 * 1024)  # ~500 MB
for i in range(0, len(data), 4096):
    data[i] = 1
time.sleep(0.5)
