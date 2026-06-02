# DocuWare to Canvas Submission Script

## Overview

This script automates the submission of student exam scripts from **DocuWare** to **Canvas LMS**. It runs continuously, checking every 5 minutes for documents in DocuWare with a status of `Process` and automatically submitting them to the correct Canvas assignment on behalf of the student.

---

## How It Works

```
DocuWare (STATUS = Process)
    ↓ Download PDF to local folder
        ↓ Create Canvas upload session
            ↓ Upload file to Canvas Inst-FS storage
                ↓ Submit file to Canvas assignment
                    ↓ Update DocuWare fields with results
                        ↓ Delete local temp file
```

---

## Prerequisites

### Python
- Python 3.8 or higher
- Download from: https://www.python.org/downloads/

### Required Libraries
Install using pip:
```
pip install requests schedule pywin32
```

### Network Access
- Must have access to `colourtech.docuware.cloud`
- Must have access to `stadio.instructure.com`
- Must have access to `login-emea.docuware.cloud`

---

## Configuration

Open `scriptsubmission.py` and update the following values at the top of the file:

| Variable | Description | Example |
|---|---|---|
| `DOCUWARE_BASE` | DocuWare cloud URL | `https://colourtech.docuware.cloud` |
| `IDENTITY_URL` | DocuWare identity service token URL | `https://login-emea.docuware.cloud/...` |
| `FILECABINET_ID` | DocuWare file cabinet GUID | `25e5f964-c45d-4ae7-...` |
| `CANVAS_DOMAIN` | Canvas LMS domain | `https://stadio.instructure.com` |
| `CANVAS_TOKEN` | Canvas API access token | `16565~xxxxx` |
| `USERNAME` | DocuWare username | `QBSAdmin` |
| `PASSWORD` | DocuWare password | `yourpassword` |
| `DOWNLOAD_DIR` | Local folder for temp file downloads | `C:\Python Script\FilestoUpload` |

---

## Required DocuWare Index Fields

The following fields must exist on each document in the file cabinet:

| Field Name | Type | Description |
|---|---|---|
| `STATUS` | String | Workflow status — set to `Process` to trigger submission |
| `STUDENT_NUMBER` | String | Student number e.g. `EM100357` |
| `MODULECODE` | String | Module code e.g. `CBE262` |
| `COURSEID` | Int | Canvas course ID |
| `ASSIGNMENTID` | Int | Canvas assignment ID |
| `USERID` | String | Canvas user ID of the student |
| `SUBMITED_FILE_SIZE` | Int | Updated by script after submission |
| `UPLOAD_URL_TEXT` | String (255) | Truncated upload URL stored by script |
| `UPLOAD_URL_MEMO` | Memo | Full upload URL stored by script |
| `UPLOADED_FILEID` | String | Canvas file ID stored by script |
| `RESULTS_INITIATE_UPLOAD_CODE` | String | HTTP code from init upload step |
| `RESULTS_INITIATE_UPLOAD_STATU` | String | HTTP reason from init upload step |
| `RESULTS_UPLOAD_FILE_CODE` | String | HTTP code from file upload step |
| `RESULTS_UPLOAD_FILE_STATUS` | String | HTTP reason from file upload step |
| `RESULTS_SUBMIT_FILE_CODE` | String | HTTP code from submission step |
| `RESULTS_SUBMIT_FILE_STATUS` | String | HTTP reason from submission step |

---

## Folder Structure

```
C:\Python Script\
    scriptsubmission.py       ← main script
    submission_service.py     ← Windows service wrapper
    run_submission.bat        ← batch file for Task Scheduler
    FilestoUpload\            ← temp folder for downloaded PDFs
    Logs\
        submission_2026-05-25.txt   ← daily submission logs
        service_2026-05-25.txt      ← service-specific logs
        scheduler.log               ← Task Scheduler output log
```

---

## How to Run

### Option A — Run directly from command prompt
```
python "C:\Python Script\scriptsubmission.py"
```
To stop press `Ctrl+C`.

---

## Deployment

### Option 1 — Windows Task Scheduler

Best for running on a schedule at specific times.

#### Step 1 — Create batch file
Create `run_submission.bat` in `C:\Python Script\`:

```batch
@echo off
echo Starting DocuWare Canvas Submission Script...
cd /d "C:\Python Script"
python scriptsubmission.py >> "C:\Python Script\Logs\scheduler.log" 2>&1
```

#### Step 2 — Set up Task Scheduler

1. Open **Task Scheduler** from the Start menu
2. Click **Create Task**
3. Fill in the tabs:

**General tab:**
```
Name:        DocuWare Canvas Submission
Description: Submits exam scripts from DocuWare to Canvas LMS
Run whether user is logged on or not: ✅ checked
Run with highest privileges: ✅ checked
```

**Triggers tab → New:**
```
Begin the task: At startup
Repeat task every: 5 minutes
For a duration of: Indefinitely
Enabled: ✅ checked
```

**Actions tab → New:**
```
Action:     Start a program
Program:    C:\Python Script\run_submission.bat
Start in:   C:\Python Script
```

**Settings tab:**
```
Allow task to be run on demand: ✅ checked
If the task fails, restart every: 1 minute
Attempt to restart up to: 3 times
Force stop if task does not end when requested: ✅ checked
```

4. Click **OK** and enter your Windows password when prompted

---

### Option 2 — Windows Service (Recommended for Production)

Runs permanently in the background. Starts automatically with Windows and restarts itself if it crashes.

#### Step 1 — Install pywin32
```
pip install pywin32
```

#### Step 2 — Update scriptsubmission.py

Make sure the bottom of `scriptsubmission.py` has the `if __name__ == "__main__"` guard so it can be safely imported by the service:

```python
if __name__ == "__main__":
    check_and_process()
    schedule.every(5).minutes.do(check_and_process)
    log.info("Scheduler running — checking every 5 minutes. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)
```

#### Step 3 — Install the service
Open **Command Prompt as Administrator** and run:

```
cd "C:\Python Script"
python submission_service.py install
```

Expected output:
```
Installing service DocuWareCanvasService
Service installed
```

#### Step 4 — Start the service
```
python submission_service.py start
```

Expected output:
```
Starting service DocuWareCanvasService
Service started
```

#### Step 5 — Set automatic restart on failure
```
sc failure DocuWareCanvasService reset= 86400 actions= restart/5000/restart/5000/restart/5000
```
This restarts the service automatically up to 3 times if it crashes, waiting 5 seconds between each restart.

#### Step 6 — Verify service is running
```
python submission_service.py status
```
Or open `services.msc` and look for **DocuWare Canvas Submission Service** — status should show **Running**.

---

### Service Management Commands

Run these from Command Prompt as Administrator in `C:\Python Script\`:

| Command | What it does |
|---|---|
| `python submission_service.py install` | Install the service |
| `python submission_service.py start` | Start the service |
| `python submission_service.py stop` | Stop the service |
| `python submission_service.py restart` | Restart the service |
| `python submission_service.py remove` | Uninstall the service |
| `python submission_service.py status` | Check service status |

---

### Closing the Command Prompt

Closing the command prompt after starting the service has **no effect** — the service keeps running in the background under Windows Service Control Manager.

| Scenario | Service status |
|---|---|
| Close command prompt | ✅ Keeps running |
| Log off Windows | ✅ Keeps running |
| Restart PC | ✅ Starts automatically on boot |
| Shutdown PC | ⏹ Stops — starts again on next boot |
| Service crashes | ✅ Restarts automatically |
| `python submission_service.py stop` | ⏹ Stops |

---

### Deployment Comparison

| | Task Scheduler | Windows Service |
|---|---|---|
| Setup difficulty | Easy | Medium |
| Runs without login | ✅ Yes | ✅ Yes |
| Starts with Windows | ✅ Yes | ✅ Yes |
| Auto restarts on crash | ❌ No (needs config) | ✅ Yes |
| Visible in Services manager | ❌ No | ✅ Yes |
| Best for | Simple scheduled runs | Production deployment |

---

## What the Script Does Step by Step

### Step 1 — Search DocuWare
Searches the file cabinet for all documents where `STATUS = Process`, sorted by document ID ascending (oldest first).

### Step 2 — Download File
Downloads the PDF from DocuWare to `C:\Python Script\FilestoUpload\` and names it `{STUDENT_NUMBER}_{MODULECODE}.pdf` e.g. `EM100357_CBE262.pdf`.

### Step 3 — Initialise Canvas Upload
Creates an upload session in Canvas for the specific course, assignment, and student. Returns a pre-signed `upload_url` and `upload_params`.

### Step 4 — Upload File to Canvas
Posts the PDF binary to the Canvas Inst-FS storage URL. No authorization header is needed as the URL is pre-signed. Returns a Canvas file ID.

### Step 5 — Submit to Canvas Assignment
Attaches the uploaded file to the student's Canvas assignment submission using the file ID from Step 4.

### Step 6 — Update DocuWare Fields
Always runs — even if a previous step failed. Updates the following fields:

| Outcome | STATUS field value |
|---|---|
| All steps succeeded | `Submitted` |
| Any step failed | `Error` |

### Cleanup
Deletes the local temp PDF file from `FilestoUpload\` after processing regardless of success or failure.

---

## Scheduler

The script runs immediately on startup then checks every 5 minutes automatically:

```
Startup → run immediately
Every 5 minutes → check for STATUS = Process documents
```

To change the interval edit this line in the script:
```python
schedule.every(5).minutes.do(check_and_process)        # every 5 minutes
schedule.every(1).hours.do(check_and_process)           # every hour
schedule.every().day.at("08:00").do(check_and_process)  # daily at 8am
```

---

## Log Files

A new log file is created daily in `C:\Python Script\Logs\` named by date:

```
submission_2026-05-25.txt
```

Example log output:
```
==================================================
Submission run started: 2026-05-25 08:30:00
==================================================
==================================================
Processing Doc ID: 316
Student: EM100357 | Module: CBE262
Course: 18455 | Assignment: 366253 | User: 38318
Download started:   08:30:01
Download ended:     08:30:03 (2.14s)
Downloaded: EM100357_CBE262.pdf (4846272 bytes)
Upload started:     08:30:03
Upload ended:       08:30:05 (1.87s)
Canvas upload session created
Upload status: 201
Uploaded File ID: 9313708
Submission started: 08:30:05
Submission ended:   08:30:06 (0.95s)
Doc 316 successfully submitted to Canvas!
DocuWare STATUS updated for Doc 316: Submitted
Canvas File ID:  9313708
Initiate Upload: 200 OK
Upload File:     201 Created
Submit File:     201 Created
Cleaned up: C:\Python Script\FilestoUpload\EM100357_CBE262.pdf
==================================================
Run Summary
==================================================
Run started:        2026-05-25 08:30:00
Run ended:          2026-05-25 08:30:06
Total duration:     6.21s
==================================================
Total documents:    5
Successful:         4
Failed:             1
Skipped:            0
Accuracy:           80.0%
==================================================
```

---

## Error Handling

| Error | Behaviour |
|---|---|
| Missing DocuWare fields | Document is skipped, logged as warning |
| Download fails | Error logged, DocuWare STATUS set to `Error` |
| Canvas upload fails | Error logged, DocuWare STATUS set to `Error` |
| Canvas submission fails | Error logged, DocuWare STATUS set to `Error` |
| DocuWare update fails | Error logged, processing continues to next document |
| DocuWare token expires | Token automatically refreshed before each operation |

---

## Canvas Requirements

- The Canvas integration account must be **enrolled as a student** in the course, or have **"Become other users"** permission enabled to submit on behalf of students
- The Canvas assignment must have **online upload** enabled as a submission type
- The Canvas assignment must be **published** and **not locked**

---

## DocuWare Requirements

- Documents must have `STATUS = Process` to be picked up by the script
- All required index fields (`COURSEID`, `ASSIGNMENTID`, `USERID`, `STUDENT_NUMBER`, `MODULECODE`) must be populated
- The DocuWare user (`QBSAdmin`) must have read and write access to the file cabinet

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| `410 Gone` on login | Wrong identity URL | Check `IDENTITY_URL` in config |
| `401 Unauthorized` on Canvas | Invalid or expired Canvas token | Generate a new token in Canvas settings |
| `403 Forbidden` on submission | Account not enrolled as student | Enroll integration account as student in Canvas |
| `No documents found` | No documents with `STATUS = Process` | Check DocuWare documents are correctly indexed |
| `Upload failed — no file ID` | File upload to Inst-FS failed | Check network access to Canvas storage |
| DocuWare fields not updating | Wrong field name | Verify field names match exactly in DocuWare |
| `Service does not exist` on start | Service not installed yet | Run `python submission_service.py install` first |
| Service fails to install | Not running as Administrator | Re-open Command Prompt as Administrator |
| Service crashes on start | Import error in scriptsubmission.py | Check `Logs\service_YYYY-MM-DD.txt` for details |
