# TP Automation

A small Streamlit interface around the automation in `ocs/importer.py`. The core
TP extraction and SIAO-generation behaviour is preserved.

## Run locally

1. Create and activate a Python virtual environment.
2. Install `requirements.txt`.
3. Set `TP_COOKIE_PASSWORD` to a long random value.
4. Either enter your own OpenAI API key on **AI TP reader**, or set
   `OPENAI_API_KEY` as an optional server fallback.
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

### Use your own OpenAI key

The **AI TP reader** includes a password-style **Your OpenAI API key** field.
The entered key takes priority over a deployment key and lasts only for the
active Streamlit session. It is never copied into `config.yaml`, browser
cookies, generated downloads, or application logs.

1. Open the official [OpenAI API key page](https://platform.openai.com/api-keys).
2. Create a new secret key and copy it when it is shown.
3. Paste it into **Your OpenAI API key** in the app.
4. Upload the training plan and select **Extract editable schedule with AI**.
5. Select **Forget key** when the session is finished, especially on a shared
   computer.

See OpenAI's official guides for
[finding an API key](https://help.openai.com/en/articles/4936850-where-do-i-find-my-api-key)
and [keeping API keys safe](https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety).

For spreadsheets that depend on drawings, embedded pictures, or charts, export
the workbook to PDF first. PDF input includes page images, while spreadsheet
input focuses on cell data and reads up to the first 1,000 rows of each sheet.

### Local GPT development test

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
2. Add your API key to the local `OPENAI_API_KEY` value. The real secrets file
   is ignored by Git; do not add the key to `config.yaml`.
3. Run the safe synthetic end-to-end test:

   ```powershell
   .\.venv\Scripts\python.exe scripts\dev_gpt_smoke.py
   ```

The command makes one GPT request, validates the editable event rows, and runs
the SIAO and OCS/SAFTI booking functions locally. Results are written to
`outputs/dev_gpt_smoke/`, which is also ignored by Git. To intentionally test a
real plan instead, add `--input "C:\path\to\training-plan.pdf"`; that selected
file will be sent to OpenAI.

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

## CE & Signals allocations

The SIAO generator fills `(Fill In) CE & Signals` in the workbook selected by
`paths.siao_template`. Both the legacy TP importer and reviewed AI events use
the same rules. The main template is never overwritten. The app generates a
downloadable copy; direct `Extractor.draft_siao` calls save to
`outputs/draft_siao.xlsx` or an explicit, separate `output_path`.

Project defaults are stored in `ocs/ce_signals.yaml`, selected by
`paths.ce_signals_rules` in `ocs/config.yaml`. Equipment quantities use exact
fractions of the 140-cadet reference, with rounding up after scaling. Diesel is
fixed at 20 L and generator at 1, sharing the Relentless-through-GPMG window.
Compasses stay allocated through the last dekitting day. LANCER does not
trigger equipment allocations. Unassigned late-November radio/MCN quantities
are retained in the rules file but are not scheduled.

Open **Settings → CE & Signals** to edit baseline cadets, quantities, fixed or
scaled allocation, and booking activities/date offsets. Changes are saved as
compact `ce_signals` overrides in browser settings and included in **Download
local config**; the shared project defaults are not overwritten. Generate a
fresh SIAO draft after saving. **Reset to config.yaml** restores project defaults.

Booking offsets reproduce the supplied October/November reference windows;
they are editable assumptions, not confirmed issue/return policies. Activities
are matched in the unfiltered training timetable so dekitting and unmatched
lessons remain available. Missing activity anchors produce review messages
rather than fabricated dates. A missing dekitting date falls back to the last
date supplied in the timetable and is reported in the app.

## Hosting notes

Streamlit needs a continuously running Python service and a WebSocket connection.
Use a Streamlit-compatible host such as Streamlit Community Cloud, Render,
Railway, Fly.io, or a container host. Vercel's normal serverless functions are
not a good fit for this app.

Set `TP_COOKIE_PASSWORD` as a host secret and keep it stable across deploys.
`OPENAI_API_KEY` is optional: set it only if the deployment should provide a
shared fallback when a user has not entered a personal session key. AI
extraction is locked to `gpt-5.6-luna`; there is no model override. Never place
an API key in `ocs/config.yaml`, browser cookies, or a downloadable local
configuration file.
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
4. In the app's Secrets settings, add a long, stable `TP_COOKIE_PASSWORD`.
   Optionally add `OPENAI_API_KEY` as a shared fallback; otherwise users enter
   their own key on **AI TP reader**. The application always uses
   `gpt-5.6-luna`.
5. Deploy the app. Use **AI TP reader** for flexible PDFs, images, and
   spreadsheets, or open **Settings** to upload a TP for the original reader.

The repository includes the default lesson plan, SIAO template, and conduct
catalogue because the app offers them as downloads. It intentionally does not
include an operational TP; each user supplies that file through the uploader.

## Code layout

`app.py` is intentionally only the Streamlit entry point. Responsibilities are
split into focused classes and modules:

- `tp_app/application.py` — application shell and page routing.
- `tp_app/context.py` — browser configuration, session state, and uploaded files.
- `tp_app/openai_access.py` — session-only personal API-key selection.
- `tp_app/ingestion/extractor.py` — `TrainingPlanExtractor` and OpenAI requests.
- `tp_app/ingestion/sources.py` — supported file preparation and PDF chunk prompts.
- `tp_app/ingestion/review.py` — `ReviewedEventValidator` for editable AI rows.
- `tp_app/catalogue_mapper.py` — YAML-to-table catalogue conversion.
- `tp_app/pages/` — one page class per Streamlit workspace.
- `ocs/training_plan_importer.py` — `TrainingPlanImporter` public class.
- `ocs/siao_extractor.py` — `SIAOExtractor` public class.
- `ocs/conduct_catalogue.py` and `ocs/booking_service.py` — focused service classes.
- `ocs/importer.py` and `ai_ingestion.py` — small compatibility entry points for
  existing scripts and tests.

`ocs/legacy_importer.py` preserves the proven workbook implementation beneath
the new class boundaries. This keeps the many fixed template-cell rules stable
while new work can target the focused modules instead of adding more code to a
single entry-point file.
