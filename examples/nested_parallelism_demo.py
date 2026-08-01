"""Simulates the classic mistake: N worker processes, each also opening
M threads internally (e.g. multiprocessing + a threaded BLAS)."""
import multiprocessing as mp
import threading
import time


def busy(_):
    time.sleep(0.6)


def worker(n_threads):
    threads = [threading.Thread(target=busy, args=(None,)) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    n_processes = 4
    n_threads_per_process = 4
    with mp.Pool(n_processes) as pool:
        pool.map(worker, [n_threads_per_process] * n_processes)
