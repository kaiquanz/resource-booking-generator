# TP Automation

A small Streamlit interface around the automation in `ocs/importer.py`. The core
TP extraction and SIAO-generation behaviour is preserved.

## Run locally

1. Create and activate a Python virtual environment.
2. Install `requirements.txt`.
3. Set `TP_COOKIE_PASSWORD` to a long random value.
4. Start the app with `streamlit run app.py`.

The Settings page begins with the values in `ocs/config.yaml`. When a user saves
changes, the app keeps an encrypted copy in that browser rather than rewriting
the repository file.

The training plan, lesson plan, SIAO template, and conduct catalogue can each be
downloaded or replaced from the Settings page. Browser uploads are copied into
temporary session storage, so users can drag and drop files without exposing an
absolute path from their computer.

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

Set `TP_COOKIE_PASSWORD` as a host secret and keep it stable across deploys.
`ocs/config.yaml` is loaded relative to `app.py`. File paths inside it may be
absolute for local use or relative to the repository root for hosted use.
Repository-relative paths work unchanged on Streamlit Community Cloud.
Generated drafts use temporary server storage and should be downloaded from the
browser.

## Deploy on Streamlit Community Cloud

### Deploy your own fork

1. Select **Fork** on GitHub to create a copy of this repository under your own account.
2. In Streamlit Community Cloud, create an app from your forked repository.
3. Select `app.py` as the entrypoint.
4. Add a long, stable `TP_COOKIE_PASSWORD` in the app's Secrets settings.
5. Deploy the app, open **Settings**, and upload a TP before generating a draft.

The repository includes the default lesson plan, SIAO template, and conduct
catalogue because the app offers them as downloads. It intentionally does not
include an operational TP; each user supplies that file through the uploader.
