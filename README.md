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
pip install requests schedule
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
    FilestoUpload\            ← temp folder for downloaded PDFs
    Logs\                     ← daily log files
        submission_2026-05-25.txt
        submission_2026-05-26.txt
        ...
```

---

## How to Run

Open a terminal and run:

```
python "C:\Python Script\scriptsubmission.py"
```

To stop the script press `Ctrl+C`.

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
schedule.every(5).minutes.do(check_and_process)   # every 5 minutes
schedule.every(1).hours.do(check_and_process)      # every hour
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
Downloaded: EM100357_CBE262.pdf (4846272 bytes)
Canvas upload session created
Upload status: 201
Uploaded File ID: 9313708
Doc 316 successfully submitted to Canvas!
DocuWare STATUS updated for Doc 316: Submitted
Canvas File ID:  9313708
Initiate Upload: 200 OK
Upload File:     201 Created
Submit File:     201 Created
Cleaned up: C:\Python Script\FilestoUpload\EM100357_CBE262.pdf
==================================================
All documents processed
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
