# cw-lens 🔍

Fast and simple search for AWS CloudWatch logs — built for checking **Email** and **IMS** logs without writing queries by hand.

## Setup
1. Install Python 3.10+ (on Windows/Mac from python.org — it includes Tkinter), then `pip install -r requirements.txt`
2. Make sure AWS credentials work (`aws configure` or `aws sso login`).
   The user/role needs `logs:StartQuery`, `logs:GetQueryResults`, `logs:StopQuery`, `logs:DescribeLogGroups`.
3. Edit `config.yaml`: set your region and the real log group names for `email` and `ims`.
   Not sure of the names? Run `python cli.py groups` to list them.

## Desktop app (recommended)
Run it directly: `python desktop.py`

Or build a double-click app:
- **Windows:** double-click `build_windows.bat` → `dist\CloudWatchLogSearch.exe`
- **Mac:** run `./build_mac.sh` → `dist/CloudWatchLogSearch.app`
- **GitHub:** push this folder to a repo; `.github/workflows/build-desktop.yml` builds both and
  attaches them to the run under "Artifacts".

First time: choose **Email**, click **Log groups…**, tick your email log groups, then do the same for **IMS**.
Your choices are saved in `~/.cloudwatch-log-search/config.yaml` (edit it to add saved queries).

## Email (SES) search
The **Email (SES)** source reads the `aws-ses-event-logs` log group and shows
Time, Event, Reason, From, To, CC, Subject and Message ID.

- Type an email address, subject or message ID and press **Enter**. It matches anywhere
  in the SES event, so BCC and every recipient are covered, not just the first "To".
- **Show** narrows to *Problems only* (bounce, complaint, reject, delay), *Bounces*, *Delivered*, …
- **Time → Custom dates…** searches an exact date range (your local time).
- Saved queries: find by address, find by subject, bounces/complaints/rejects, delivery delays,
  event counts per day.

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
