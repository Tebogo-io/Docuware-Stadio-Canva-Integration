import re
import os
import time
import shutil
import requests
import logging
import schedule
from pathlib import Path
from datetime import datetime

# =========================
# CONFIG
# =========================

DOCUWARE_BASE = "https://colourtech.docuware.cloud"
IDENTITY_URL = "https://login-emea.docuware.cloud/1ac14066-55b2-49ad-a7b3-017e1849807f/connect/token"

FILECABINET_ID = "25e5f964-c45d-4ae7-bb90-595a5c1ec76b"

USERNAME = os.getenv("DOCUWARE_USERNAME", "QBSAdmin")
PASSWORD = os.getenv("DOCUWARE_PASSWORD")

if not USERNAME or not PASSWORD:
    raise ValueError("Missing DocuWare credentials in environment variables")

BASE_DIR = Path(os.getenv("BASE_DIR", Path(__file__).resolve().parent))

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", BASE_DIR / "FilestoUpload"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


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
# DOCUWARE CLIENT
# =========================

class DocuWareClient:
    """Handles DocuWare authentication and API headers."""

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.token = None
        self.expiry = 0

    def login(self):
        """Authenticate with DocuWare Identity Service and store access token."""
        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "scope": "docuware.platform",
            "client_id": "docuware.platform.net.client"
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        res = requests.post(IDENTITY_URL, data=payload, headers=headers, timeout=30)
        res.raise_for_status()
        self.token = res.json()["access_token"]
        # Token is valid for 60 min — refresh after 55 min as safety buffer
        self.expiry = time.time() + 55 * 60
        log.info("DocuWare login successful")

    def ensure_auth(self):
        """Re-login if token is missing or expired."""
        if not self.token or time.time() > self.expiry:
            log.info("Refreshing DocuWare session...")
            self.login()

    def get_headers(self):
        """Return Authorization headers for DocuWare API calls."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }


# =========================
# INIT CLIENT
# =========================

# Create DocuWare client and login on startup
dw = DocuWareClient(USERNAME, PASSWORD)
dw.login()

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# =========================
# MAIN PROCESS FUNCTION
# =========================

def check_and_process():

    # Archive old logs at the start of each run
    # This ensures if the script runs past midnight logs are archived
    archive_old_logs()

    # Track accuracy counters for this run
    total_docs = 0
    successful_docs = 0
    failed_docs = 0
    skipped_docs = 0

    # Track overall run time
    run_start = datetime.now()

    log.info(f"{'='*50}")
    log.info(f"Submission run started: {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"{'='*50}")

    # -------------------------
    # SEARCH — STATUS = Process
    # -------------------------

    # Refresh token if needed before searching
    dw.ensure_auth()

    search_response = requests.post(
        f"{DOCUWARE_BASE}/DocuWare/Platform/FileCabinets/{FILECABINET_ID}/Query/DialogExpression",
        headers=dw.get_headers(),
        json={
            "Condition": [
                {
                    "DBName": "STATUS",
                    "Value": ["Process"]  # only fetch documents ready to be processed
                }
            ],
            "Operation": "And",
            "SortOrder": [
                {
                    "Field": "DWDOCID",
                    "Direction": "Asc"  # process oldest documents first
                }
            ]
        }
    )
    search_response.raise_for_status()

    # Extract document list from response
    documents = search_response.json().get("Items", [])

    if not documents:
        log.info("No documents found with STATUS = Process")
        log.info(f"Run ended: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return

    total_docs = len(documents)
    log.info(f"Found {total_docs} document(s) to process")

    # -------------------------
    # LOOP — PROCESS EACH DOC
    # -------------------------

    for doc in documents:

        # Extract all index fields into a dictionary for easy access
        fields = {f["FieldName"]: f.get("Item") for f in doc.get("Fields", [])}
        DOC_ID = doc.get("Id")

        # Get required fields from DocuWare document
        COURSE_ID = fields.get("COURSEID")
        ASSIGNMENT_ID = fields.get("ASSIGNMENTID")
        USER_ID = fields.get("USERID")
        STUDENT_NUMBER = fields.get("STUDENT_NUMBER")
        MODULE_CODE = fields.get("MODULECODE")
        TEST_NUMBER = fields.get("BOTTONNUMBER", "")
        CANVAS_DOMAIN = fields.get("CANVASDOMAIN")
        CANVAS_TOKEN = fields.get("ACCESSTOKEN")

        # Canvas API headers used for all Canvas requests
        canvas_headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"}

        log.info(f"{'='*50}")
        log.info(f"Processing Doc ID: {DOC_ID}")
        log.info(f"Student: {STUDENT_NUMBER} | Module: {MODULE_CODE} | Test Number: {TEST_NUMBER}")
        log.info(f"Course: {COURSE_ID} | Assignment: {ASSIGNMENT_ID} | User: {USER_ID}")

        # Skip document if any required field is missing
        if not all([COURSE_ID, ASSIGNMENT_ID, USER_ID, STUDENT_NUMBER, MODULE_CODE]):
            log.info(f"Skipping Doc {DOC_ID} — missing required fields")
            skipped_docs += 1
            continue

        # Build filename — sanitize to remove invalid Windows path characters
        # e.g. forward slash in dates like 5/27/2026 would break the file path
        raw_file_name = f"{STUDENT_NUMBER}_{MODULE_CODE}_{TEST_NUMBER}"
        FILE_NAME = re.sub(r'[<>:"/\\|?*]', '_', raw_file_name) + ".pdf"
        FILE_PATH = os.path.join(DOWNLOAD_DIR, FILE_NAME)

        # Initialise all variables before try block so they always
        # exist in the finally block even if a step fails early
        init_response = None
        upload_response = None
        submit_response = None
        upload_url = ""
        file_size = 0
        UPLOAD_FILE_ID = None
        doc_success = False
        error_message = ""
        error_status = "Error - Webservice"  # default error status if no specific step fails

        # Stores Canvas error response bodies if steps fail
        init_error_body = ""
        upload_error_body = ""
        submit_error_body = ""

        try:
            # -------------------------
            # STEP 2 — DOWNLOAD FILE
            # -------------------------
            # Refresh token before downloading
            dw.ensure_auth()

            download_start = datetime.now()
            log.info(f"Download started:   {download_start.strftime('%H:%M:%S')}")

            # Set error status to downloading — if this step fails
            # DocuWare will be updated with "Error - Downloading"
            error_status = "Error - Downloading"

            file_response = requests.get(
                f"{DOCUWARE_BASE}/DocuWare/Platform/FileCabinets/{FILECABINET_ID}"
                f"/Documents/{DOC_ID}/FileDownload?targetFileType=Auto&keepAnnotations=false",
                headers=dw.get_headers()
            )
            file_response.raise_for_status()

            # Save file to local download directory
            with open(FILE_PATH, "wb") as f:
                f.write(file_response.content)

            download_end = datetime.now()
            download_duration = (download_end - download_start).total_seconds()
            file_size = os.path.getsize(FILE_PATH)
           


            log.info(f"Download ended:     {download_end.strftime('%H:%M:%S')} ({download_duration:.2f}s)")
            log.info(f"Downloaded: {FILE_NAME} ({file_size} bytes)")

            # -------------------------
            # STEP 3 — INIT CANVAS UPLOAD
            # -------------------------
            # Tell Canvas we are about to upload a file
            # Returns upload_url and upload_params needed for Step 4

            upload_start = datetime.now()
            log.info(f"Upload started:     {upload_start.strftime('%H:%M:%S')}")

            # Set error status to uploading — if this step fails
            # DocuWare will be updated with "Error - Uploading"
            error_status = "Error - Uploading"

            init_response = requests.post(
                f"{CANVAS_DOMAIN}/api/v1/courses/{COURSE_ID}"
                f"/assignments/{ASSIGNMENT_ID}/submissions/{USER_ID}/files",
                headers=canvas_headers,
                data={
                    "name": FILE_NAME,
                    "size": file_size,
                    "content_type": "application/pdf"
                }
            )
            init_response.raise_for_status()
            
            upload_data = init_response.json()
            upload_url = upload_data["upload_url"]        # Inst-FS URL to upload to
            upload_params = upload_data["upload_params"]  # Params required by Inst-FS
            log.info("Canvas upload session created")
            try:
                dw.ensure_auth()

          
                ifields_to_update = [
                    {
                        # HTTP status code from Step 3 (init upload)
                        "FieldName": "RESULTS_INITIATE_UPLOAD_CODE",
                        "Item": str(init_response.status_code) if init_response else "NULL",
                        "ItemElementName": "String"
                    },
                    {
                        # HTTP reason + error body from Step 3 (init upload)
                        # Note: DocuWare field name is truncated to STATU not STATUS
                        "FieldName": "RESULTS_INITIATE_UPLOAD_STATU",
                        "Item": f"{init_response.reason} {init_error_body}".strip() if init_response else "N/A",
                        "ItemElementName": "String"
                    },
                ]
                                # Only add upload URL if upload session was created
                if upload_url:
                    ifields_to_update.append({
                        # Truncated to 2000 chars for String field
                        "FieldName": "UPLOAD_URL_TEXT",
                        "Item": upload_url[:2000],
                        "ItemElementName": "String"
                    })
                    ifields_to_update.append({
                        # Full URL stored in Memo field (no character limit)
                        "FieldName": "UPLOAD_URL_MEMO",
                        "Item": upload_url,
                        "ItemElementName": "Memo"
                    })

                      # Send all field updates to DocuWare in one request
                iupdate_response = requests.put(
                    f"{DOCUWARE_BASE}/DocuWare/Platform/FileCabinets/{FILECABINET_ID}"
                    f"/Documents/{DOC_ID}/Fields",
                    headers=dw.get_headers(),
                    json={"Field": ifields_to_update}
                )
                iupdate_response.raise_for_status()
                log.info(f"Initiate Upload: {init_response.status_code if init_response else 'N/A'} {init_response.reason if init_response else ''} {init_error_body[:100] if init_error_body else ''}")
            
            except Exception as inupdate_error:
                # Log if DocuWare update itself fails
                log.error(f"Failed to update DocuWare initiate upload fieds for Doc {DOC_ID}: {inupdate_error}")

            
            # -------------------------
            # STEP 4 — UPLOAD FILE
            # -------------------------
            # POST file binary to Inst-FS storage
            # No Authorization header needed — upload_url is pre-signed
            with open(FILE_PATH, "rb") as f:
                upload_response = requests.post(
                    upload_url,
                    data=upload_params,
                    files={"file": (FILE_NAME, f, "application/pdf")},
                    allow_redirects=False  # do not follow redirect automatically
                )

            upload_end = datetime.now()
            upload_duration = (upload_end - upload_start).total_seconds()

            log.info(f"Upload ended:       {upload_end.strftime('%H:%M:%S')} ({upload_duration:.2f}s)")
            log.info(f"Upload status: {upload_response.status_code}")


            try:
                dw.ensure_auth()

          
                ufields_to_update = [
                     {
                        # HTTP status code from Step 4 (file upload)
                        "FieldName": "RESULTS_UPLOAD_FILE_CODE",
                        "Item": str(upload_response.status_code) if upload_response else "NULL",
                        "ItemElementName": "String"
                    },
                    {
                        # HTTP reason + error body from Step 4 (file upload)
                        "FieldName": "RESULTS_UPLOAD_FILE_STATUS",
                        "Item": f"{upload_response.reason} {upload_error_body}".strip() if upload_response else "N/A",
                        "ItemElementName": "String"
                    }
                ]
              
               
                      # Send all field updates to DocuWare in one request
                uupdate_response = requests.put(
                    f"{DOCUWARE_BASE}/DocuWare/Platform/FileCabinets/{FILECABINET_ID}"
                    f"/Documents/{DOC_ID}/Fields",
                    headers=dw.get_headers(),
                    json={"Field": ufields_to_update}
                )
                uupdate_response.raise_for_status()
                log.info(f"Upload File:     {uupdate_response.status_code if upload_response else 'N/A'} {upload_response.reason if upload_response else ''} {upload_error_body[:100] if upload_error_body else ''}")
            
            except Exception as unupdate_error:
                # Log if DocuWare update itself fails
                log.error(f"Failed to update DocuWare upload file fieds for Doc {DOC_ID}: {unupdate_error}")



            # Extract Canvas file ID from upload response
            try:
                UPLOAD_FILE_ID = upload_response.json().get("id")
            except Exception:
                UPLOAD_FILE_ID = None

            if not UPLOAD_FILE_ID:
                raise Exception("Upload failed — no file ID returned")

            log.info(f"Uploaded File ID: {UPLOAD_FILE_ID}")

            # -------------------------
            # STEP 5 — SUBMIT TO CANVAS
            # -------------------------
            # Attach uploaded file to the Canvas assignment submission

            submit_start = datetime.now()
            log.info(f"Submission started: {submit_start.strftime('%H:%M:%S')}")

            # Set error status to submission — if this step fails
            # DocuWare will be updated with "Error - Submission"
            error_status = "Error - Submission"

            submit_response = requests.post(
                f"{CANVAS_DOMAIN}/api/v1/courses/{COURSE_ID}"
                f"/assignments/{ASSIGNMENT_ID}/submissions",
                headers=canvas_headers,
                data={
                    "submission[submission_type]": "online_upload",
                    "submission[file_ids][]": UPLOAD_FILE_ID,
                    "submission[user_id]": USER_ID
                }
            )
            submit_response.raise_for_status()

            submit_end = datetime.now()
            submit_duration = (submit_end - submit_start).total_seconds()

            log.info(f"Submission ended:   {submit_end.strftime('%H:%M:%S')} ({submit_duration:.2f}s)")
            log.info(f"Doc {DOC_ID} successfully submitted to Canvas!")

            # Mark document as successfully processed
            doc_success = True
            successful_docs += 1

        except Exception as e:
            # Log error — Step 6 will still run in finally block
            
            log.error(f"Error processing Doc {DOC_ID}: {e}")
            failed_docs += 1
            error_message = str(e)

            # Capture response body from whichever step failed
           
            try:
                if init_response is not None and not init_response.ok:
                    init_error_body = init_response.text[:500]
                if upload_response is not None and not upload_response.ok:
                    upload_error_body = upload_response.text[:500]
                if submit_response is not None and not submit_response.ok:
                    submit_error_body = submit_response.text[:500]
            except Exception:
                pass

        finally:
            # -------------------------
            # STEP 6 — UPDATE DOCUWARE
            # -------------------------
            # Always runs whether steps succeeded or failed
           
            try:
                dw.ensure_auth()

                # Build field list — always include status and result codes
                fields_to_update = [
                    {
                    
                    
                        "FieldName": "STATUS",
                        "Item": "Submitted" if doc_success else error_status,
                        "ItemElementName": "String"
                    },
                    {
                        # Store general result — success message or full error details
                        "FieldName": "GENERAL_RESULTS",
                        "Item": (
                            f"Successfully submitted to Canvas. File ID: {UPLOAD_FILE_ID}"
                            if doc_success
                            else f"{error_status}: {error_message}"
                        ),
                        "ItemElementName": "String"
                    },
                   
                   
                    {
                        # HTTP status code from Step 5 (submission)
                        "FieldName": "RESULTS_SUBMIT_FILE_CODE",
                        "Item": str(submit_response.status_code) if submit_response else "NULL",
                        "ItemElementName": "String"
                    },
                    {
                        # HTTP reason + error body from Step 5 (submission)
                        "FieldName": "RESULTS_SUBMIT_FILE_STATUS",
                        "Item": f"{submit_response.reason} {submit_error_body}".strip() if submit_response else "N/A",
                        "ItemElementName": "String"
                    }
                ]

                               
                # Only add file size if file was actually downloaded
                if file_size > 0:
                    fields_to_update.append({
                        "FieldName": "SUBMITED_FILE_SIZE",
                        "Item": file_size,
                        "ItemElementName": "Int"
                    })



                # Only add Canvas file ID if upload succeeded
                if UPLOAD_FILE_ID:
                    fields_to_update.append({
                        "FieldName": "UPLOADED_FILEID",
                        "Item": UPLOAD_FILE_ID,
                        "ItemElementName": "Int"
                    })


                # Send all field updates to DocuWare in one request
                update_response = requests.put(
                    f"{DOCUWARE_BASE}/DocuWare/Platform/FileCabinets/{FILECABINET_ID}"
                    f"/Documents/{DOC_ID}/Fields",
                    headers=dw.get_headers(),
                    json={"Field": fields_to_update}
                )
                update_response.raise_for_status()

                log.info(f"DocuWare updated for Doc {DOC_ID}: {'Submitted' if doc_success else error_status}")
                log.info(f"General Result:  {'Success' if doc_success else error_message[:100]}")
                log.info(f"Canvas File ID:  {UPLOAD_FILE_ID if UPLOAD_FILE_ID else 'N/A'}")
               
               
                log.info(f"Submit File:     {submit_response.status_code if submit_response else 'N/A'} {submit_response.reason if submit_response else ''} {submit_error_body[:100] if submit_error_body else ''}")

            except Exception as update_error:
                # Log if DocuWare update itself fails
                log.error(f"Failed to update DocuWare for Doc {DOC_ID}: {update_error}")

            # -------------------------
            # CLEANUP — DELETE LOCAL FILE
            # -------------------------
            # Always delete temp file from local disk after processing
            if os.path.exists(FILE_PATH):
                os.remove(FILE_PATH)
                log.info(f"Cleaned up: {FILE_PATH}")

    # -------------------------
    # ACCURACY SUMMARY
    # -------------------------
    # Log processing summary at end of each run

    run_end = datetime.now()
    run_duration = (run_end - run_start).total_seconds()

    accuracy = (successful_docs / total_docs * 100) if total_docs > 0 else 0

    log.info(f"{'='*50}")
    log.info(f"Run Summary")
    log.info(f"{'='*50}")
    log.info(f"Run started:        {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Run ended:          {run_end.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Total duration:     {run_duration:.2f}s")
    log.info(f"{'='*50}")
    log.info(f"Total documents:    {total_docs}")
    log.info(f"Successful:         {successful_docs}")
    log.info(f"Failed:             {failed_docs}")
    log.info(f"Skipped:            {skipped_docs}")
    log.info(f"Accuracy:           {accuracy:.1f}%")
    log.info(f"{'='*50}")


# =========================
# RUN — IMMEDIATELY THEN
# EVERY 10 SECONDS
# =========================

if __name__ == "__main__":
    # Run once immediately on startup
    check_and_process()

    # Then schedule to run every 10 seconds
    schedule.every(10).seconds.do(check_and_process)

    log.info("Scheduler running — checking every 10 seconds.")

    # Keep script running and check for scheduled jobs every 5 seconds
    while True:
        schedule.run_pending()
        time.sleep(5)