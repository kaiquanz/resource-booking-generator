# TP Automation

A small Streamlit interface around the automation in `ocs/importer.py`. The core
TP extraction and SIAO-generation behaviour is preserved.

## Run locally

1. Create and activate a Python virtual environment.
2. Install `requirements.txt`.
3. Set `TP_COOKIE_PASSWORD` to a long random value.
4. Set `OPENAI_API_KEY` if you want to use the AI training-plan reader.
5. Start the app with `streamlit run app.py`.

The Settings page begins with the values in `ocs/config.yaml`. When a user saves
changes, the app keeps an encrypted copy in that browser rather than rewriting
the repository file.

The training plan, lesson plan, SIAO template, and conduct catalogue can each be
downloaded or replaced from the Settings page. Browser uploads are copied into
temporary session storage, so users can drag and drop files without exposing an
absolute path from their computer.

## AI training-plan reader

Open **AI TP reader** to upload a spreadsheet, PDF, scan, or timetable image.
The app asks OpenAI to convert the document into a standard event table. Users
must review and approve that editable table before the existing SIAO and booking
functions can use it. The reviewed rows can also be downloaded as CSV.

AI extraction is an aid, not a guarantee for every possible layout. Keep the
review step: visually complex, low-quality, or ambiguous plans may need manual
correction. Uploaded files are sent to OpenAI when the user selects the extract
button, so deployment owners must confirm that this is allowed by their
information-handling policy.

For spreadsheets that depend on drawings, embedded pictures, or charts, export
the workbook to PDF first. PDF input includes page images, while spreadsheet
input focuses on cell data and reads up to the first 1,000 rows of each sheet.

## Conduct catalogue

Timetable naming rules are stored in `ocs/conduct_catalog.yaml` rather than in a
Python dictionary. Open **Conduct catalogue** in the app to edit aliases,
exclusions, display names, multi-day behaviour, and active status. Keep each
`conduct_id` unchanged after it has been created; it is the stable link to the
configured lesson-plan conduct.

The catalogue is validated before saving. Conflicting aliases are treated as
ambiguous, meaningful numbers such as `4KM` are preserved, and unresolved
timetable entries are shown after SIAO generation instead of being silently
discarded.

## Hosting notes

Streamlit needs a continuously running Python service and a WebSocket connection.
Use a Streamlit-compatible host such as Streamlit Community Cloud, Render,
Railway, Fly.io, or a container host. Vercel's normal serverless functions are
not a good fit for this app.

Set `TP_COOKIE_PASSWORD` and `OPENAI_API_KEY` as host secrets. Keep the cookie
password stable across deploys. You may optionally set `OPENAI_MODEL`; it
defaults to `gpt-5.6`. Never place the API key in `ocs/config.yaml`, browser
cookies, or a downloadable local configuration file.
`ocs/config.yaml` is loaded relative to `app.py`. File paths inside it may be
absolute for local use or relative to the repository root for hosted use.
Repository-relative paths work unchanged on Streamlit Community Cloud.
Generated drafts use temporary server storage and should be downloaded from the
browser.

Firebase is not required for this workflow. Add a database or object-storage
service only if uploads, reviewed schedules, or generated documents must be
shared between users or survive session/server restarts.

If the app is public, add access control and spending/rate limits before sharing
it broadly; otherwise visitors can consume the deployment owner's API quota.

## Deploy on Streamlit Community Cloud

### Deploy your own fork

1. Select **Fork** on GitHub to create a copy of this repository under your own account.
2. In Streamlit Community Cloud, create an app from your forked repository.
3. Select `app.py` as the entrypoint.
4. In the app's Secrets settings, add a long, stable `TP_COOKIE_PASSWORD` and an
   `OPENAI_API_KEY`. `OPENAI_MODEL` is optional.
5. Deploy the app. Use **AI TP reader** for flexible PDFs, images, and
   spreadsheets, or open **Settings** to upload a TP for the original reader.

The repository includes the default lesson plan, SIAO template, and conduct
catalogue because the app offers them as downloads. It intentionally does not
include an operational TP; each user supplies that file through the uploader.
