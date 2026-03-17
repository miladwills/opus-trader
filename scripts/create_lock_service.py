import paramiko

HOST = "178.18.245.6"
USER = "root"
PASS = "aA0109587045"
TARGET_FILE = "/var/www/opus_trader/services/lock_service.py"

CONTENT = r'''import sys
import os
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Platform imports
if sys.platform == 'win32':
    import msvcrt
else:
    import fcntl

def _acquire_lock_platform(fd, exclusive=True, non_blocking=False):
    """Low-level platform specific locking."""
    if sys.platform == 'win32':
        # Windows locking
        mode = msvcrt.LK_NBLCK if non_blocking else msvcrt.LK_LOCK
        try:
            # Lock the first byte
            msvcrt.locking(fd, mode, 1)
        except OSError:
            raise BlockingIOError("Lock already held")
    else:
        # Unix locking
        flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if non_blocking:
            flags |= fcntl.LOCK_NB
        fcntl.flock(fd, flags)

def _release_lock_platform(fd):
    if sys.platform == 'win32':
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)

@contextmanager
def file_lock(lock_path, exclusive=False):
    """Context manager for file locking."""
    path_obj = Path(lock_path)
    if not path_obj.exists():
        path_obj.touch()

    # Open for update (r+) to allow locking on Windows
    f = open(path_obj, "r+")
    try:
        # On Windows, ensure file has content to lock
        if sys.platform == 'win32' and os.path.getsize(path_obj) == 0:
            f.write(' ')
            f.flush()
            f.seek(0)

        _acquire_lock_platform(f.fileno(), exclusive=exclusive, non_blocking=False)
        yield f
    finally:
        try:
            _release_lock_platform(f.fileno())
        except Exception as e:
            logger.warning(f"Error releasing lock {lock_path}: {e}")
        f.close()

def acquire_process_lock(lock_path):
    """Acquire a persistent exclusive lock (non-blocking). Returns file object or None."""
    path_obj = Path(lock_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    f = open(path_obj, "a+")
    try:
        if sys.platform == 'win32' and os.path.getsize(path_obj) == 0:
            f.write(' ')
            f.flush()

        _acquire_lock_platform(f.fileno(), exclusive=True, non_blocking=True)
        return f
    except (BlockingIOError, OSError):
        f.close()
        return None
'''

def main():
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS)
        
        print(f"Uploading {TARGET_FILE}...")
        sftp = ssh.open_sftp()
        with sftp.file(TARGET_FILE, 'w') as f:
            f.write(CONTENT)
        sftp.close()
        print("Done.")
        
        ssh.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
