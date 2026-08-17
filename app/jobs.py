"""Shared job state and thread-pool executors."""

import threading
from concurrent.futures import ThreadPoolExecutor

from app.config import MAX_WORKERS

# In-memory job store. Keys are job-id strings.
jobs: dict = {}
jobs_lock = threading.Lock()

# Download pool — bounded by MAX_WORKERS so a single user cannot saturate the
# server.
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Transcoding is CPU-bound and can run for a long time.  Keep it off the
# download pool so one re-encode cannot starve every pending download.
transcode_executor = ThreadPoolExecutor(max_workers=1)

# Probing must answer while downloads are running, so it needs its own pool.
probe_executor = ThreadPoolExecutor(max_workers=2)
