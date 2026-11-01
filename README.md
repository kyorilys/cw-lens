# cw-lens 🔍

Fast and simple search for AWS CloudWatch logs — built for checking **Email** and **IMS** logs without writing queries by hand.

## Setup
1. Install Python 3.10+ (on Windows/Mac from python.org — it includes Tkinter), then `pip install -r requirements.txt`
2. Make sure AWS credentials work (`aws configure` or `aws sso login`).
   The user/role needs `logs:StartQuery`, `logs:GetQueryResults`, `logs:StopQuery`, `logs:GetLogEvents`, `logs:DescribeLogGroups`.
3. Edit `config.yaml`: set your region and the real log group names for `email` and `ims`.
   Not sure of the names? Run `python cli.py groups` to list them.

## Desktop app (recommended)
A modern window with a sidebar for **Email** and **IMS**, a big search bar, coloured event badges,
a details panel for each log line, and light/dark themes.

Run it directly: `python webapp.py`

Or build a double-click app:
- **Windows:** double-click `build_windows.bat` → `dist\cw-lens.exe` (uses Edge WebView2, built into Windows 10/11)
- **Mac:** run `./build_mac.sh` → `dist/cw-lens.app`
- **GitHub:** every push builds both (see the run's "Artifacts").

First time: pick **IMS** in the sidebar and choose its log groups. Email is preset to `aws-ses-event-logs`.
Your choices are saved in `~/.cloudwatch-log-search/config.yaml` (edit it to add saved searches).

Tips: press `/` to jump to the search box, `↑`/`↓` to move between results, `Esc` to close panels.
Click **Query** to see or edit the exact CloudWatch Logs Insights query.

The older plain window is still available: `python desktop.py`.

## Email (SES) search
The **Email (SES)** source reads the `aws-ses-event-logs` log group and shows
Time, Event, Reason, From, To, CC, Subject and Message ID.

- Type an email address, subject or message ID and press **Enter**. It matches anywhere
  in the SES event, so BCC and every recipient are covered, not just the first "To".
- **Show** narrows to *Problems only* (bounce, complaint, reject, delay), *Bounces*, *Delivered*, …
- **Time → Custom dates…** searches an exact date range (your local time).
- Saved queries: find by address, find by subject, bounces/complaints/rejects, delivery delays,
  event counts per day.

## IMS search
IMS (the `warehouse_ims` Django app and its Celery workers) prints lines like
`[2026-10-21 08:01:02,123: ERROR/MainProcess] Courier API timeout ...`.
cw-lens splits these into **Level**, **Process** and **Message**.

- Search an order number, SKU or error text. **Show** narrows to Errors, Warnings & errors, Info,
  or Background tasks (Celery workers).
- Saved searches: recent errors, find by order/SKU/keyword, most common errors, crashes & tracebacks,
  timeouts, background task errors, errors per 5 minutes.
- The first time, click **Choose log groups** and pick the IMS log groups (try filtering for
  `ims`, `warehouse`, `ecs`, `elasticbeanstalk` or `apprunner`).
- Python errors are split into one CloudWatch line each, so a result like `Traceback (most recent call last):`
  says little on its own. Click it: the details panel loads the **surrounding lines** from the same
  log stream, so you see the whole traceback with the actual error (e.g. `IntegrityError: ...`) in red.
  **Crashes (exception lines)** finds those final error lines directly.
- IMS also keeps errors (with full tracebacks) and request logs in its own database
  (`ErrorLog`, `RequestLog`); those are not in CloudWatch.

## Web app
`streamlit run app.py` then open http://localhost:8501

- **Simple search** – type an email address, ID, or keyword; pick a level and time range.
- **Saved query** – one-click queries from `config.yaml` (`{term}` gets replaced by your search text).
- **Advanced** – write any CloudWatch Logs Insights query.
- Results can be downloaded as CSV.

## Command line
```
python cli.py search email user@example.com --since "Last 24 hours"
python cli.py search ims timeout --level ERROR
python cli.py saved email "Recent errors / bounces"
```

## Adding another log source
Add a new entry under `sources:` in `config.yaml` — it shows up in the app automatically.
