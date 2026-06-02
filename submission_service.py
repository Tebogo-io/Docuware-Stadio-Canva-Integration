import sys
import os
import time
import shutil
import logging
import threading
import schedule
import servicemanager
import win32event
import win32service
import win32serviceutil
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(os.getenv("BASE_DIR", Path(__file__).resolve().parent))
sys.path.insert(0, str(BASE_DIR))

# =========================
# LOGGING SETUP
# =========================

LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "Logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)



# Archive folder inside Logs — all previous day logs go here
ARCHIVE_DIR = Path(os.getenv("ARCHIVE_DIR", LOG_DIR / "Archive"))
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def archive_old_logs():
    """
    Move any log files that are not from today into the Archive folder.
    Keeps only today's log file in the Logs root directory.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    for log_file in LOG_DIR.glob("submission_*.txt"):
        # Only move files that are NOT today's log
        if today not in log_file.name:
            dest = ARCHIVE_DIR / log_file.name
            shutil.move(str(log_file), str(dest))
            print(f"Archived: {log_file.name} → Archive/")


# Archive old logs on startup before creating today's log
archive_old_logs()

# Create a new log file each day named by date e.g. submission_2026-05-25.txt
log_filename = LOG_DIR / f"submission_{datetime.now().strftime('%Y-%m-%d')}.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),  # write to file
        logging.StreamHandler()                                # also print to console
    ]
)

log = logging.getLogger()


# =========================
# IMPORT MAIN PROCESS
# =========================
try:
    from script_submission import check_and_process, dw
    log.info("Imported script_submission successfully")
except Exception as e:
    log.error(f"Import failed: {e}")
    sys.exit(1)


# =========================
# GLOBAL STOP EVENT
# =========================
STOP_EVENT = win32event.CreateEvent(None, 0, 0, None)


# =========================
# SCHEDULER THREAD
# =========================
def run_scheduler():
    log.info("Scheduler thread started")

    try:
        check_and_process()
    except Exception as e:
        log.error(f"Initial run error: {e}")

    # 5 minutes (PRODUCTION SAFE)
    schedule.every(5).minutes.do(check_and_process)

    while True:
        # 🔴 STOP HANDLING (IMPORTANT FIX)
        if win32event.WaitForSingleObject(STOP_EVENT, 0) == win32event.WAIT_OBJECT_0:
            log.info("Scheduler stopping...")
            break

        try:
            schedule.run_pending()
        except Exception as e:
            log.error(f"Scheduler error: {e}")

        time.sleep(5)


# =========================
# WINDOWS SERVICE
# =========================
class DocuWareCanvasService(win32serviceutil.ServiceFramework):

    _svc_name_ = "DocuWareCanvasService"
    _svc_display_name_ = "DocuWare Canvas Submission Service"
    _svc_description_ = "Automates DocuWare to Canvas submissions"

    def __init__(self, args):
        super().__init__(args)
        self.thread = None

    def SvcStop(self):
        log.info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)

        win32event.SetEvent(STOP_EVENT)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, "")
        )

        log.info("Service started")

        self.thread = threading.Thread(target=run_scheduler, daemon=True)
        self.thread.start()

        win32event.WaitForSingleObject(STOP_EVENT, win32event.INFINITE)

        log.info("Service stopped")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(DocuWareCanvasService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(DocuWareCanvasService)