# SiteScribe — item capture web app (Flask)

A phone-first capture UI built to the **App Workflow** slide and the notebook
sketch: an Item navigator over a photo, a Photo navigator under it.

> **Note for the team:** this Flask app is the main SiteScribe app. The
> Streamlit app that used to live on `main` is retired. The `sitescribe/`
> modules plug in behind these routes; see [INTEGRATION_PLAN.md](../INTEGRATION_PLAN.md).
> From the repo root, `python run.py` starts this same server.

## Live

**https://planning-matrix-bacteria-occupation.trycloudflare.com** (PIN: ask the team)

Merges to the tracked branch deploy themselves within 2 minutes — see
[DEPLOY.md](../DEPLOY.md). You do not need server access to change it.

## Run locally

```bash
pip install -r requirements.txt
python server.py            # http://localhost:5000   PIN 2424
```

`localhost` is a secure context, so camera and mic work with no HTTPS.
For a phone you need a public HTTPS URL:

```bash
cloudflared tunnel --url http://localhost:5000
```

Plain HTTP on a LAN IP **silently** blocks the microphone.

## Projects and site visits

```
/                         New project · Existing project · gear → /settings
/projects/new             name, number (required), address
/projects                 every project by number, with search
/projects/<J-001>         project info, + New site visit, visits, action items
/projects/<J-001>/visits/new   visit no (latest + 1), date, by, others present,
                          stage of construction, structural elements observed
/visits/<P-001>/edit      the same fields for an existing visit
/capture                  the open visit's items
```

A project is a "job" in the code (`J-###`, `data/jobs.json`); each site visit
is a `P-###` record in `data/projects.json` with its `job_id`, so the item,
photo and plan routes below are unchanged. A new visit copies the previous
visit's plan sheets, without pins.

```
data/jobs.json                every project
data/projects.json            every site visit
data/P-001/visit.json         that visit's items + plans
uploads/P-001/001/...         its photos and audio
uploads/P-001/plans/...
```

Each entry gets a report number when it is made and keeps it: entry n of
Site Visit 2 prints as **ITEM 2.n**.

### Action items

An entry with an **Action** is an action item. From the items screen or the
project page it takes dated updates (`+ Add update`) and a **Close out**, each
aimed at a visit's report (default: the next one). A visit's report lists,
under Previous Action Items, every earlier included action item that is still
open or is closed out in that report, with its updates; the closing update
ends "No further action required." and the item drops off after that report.

A legacy single-visit `data/visit.json` is migrated into `P-001` on first
start — files moved, stored URLs re-prefixed, original mtime preserved. It is
idempotent.

## Word export

`GET /api/export/docx` converts the visit with `webapp/bridge.py` (`to_project`)
and hands it to `sitescribe.word_report.build_report`: header, summary, pinned
plan sheets, one ITEM block per included entry with its photo and caption,
action items, photo log. Only plans with a pin are rendered. If the module
raises, the traceback is logged to stderr and the built-in python-docx report
below ships instead, so the user always gets a file; the response then carries
an `X-SiteScribe-Report-Notice` header saying why.

The **Export** button uses two requests so a phone sees progress and a real
error instead of a blank tab: `POST /api/export/build` builds the bundle zip
(report, EXIF-tagged photos, pinned plan pages), keeps it as
`data/<pid>/export.zip` and answers `{url, name, bytes, seconds, notice}`; the
page then navigates to `GET /api/export/download`, which serves that file.
`GET /api/export/bundle` still builds and streams the same zip in one request.
The report is built outside the global lock, so a long export does not stall
other requests.

## Report template (formatting only)

There is **one template for the whole app**, set up once under the gear icon →
**Settings** and used by every export. It is stored
as `data/report_template.docx` (outside git) and only needs changing when the
firm's template does.

The export inherits the template's styles, fonts, margins, header/footer and
logo. A template with Jinja tags (`{{ ... }}`) is rendered by docxtpl and
decides the whole layout; see `sitescribe/word_report.py`. **No AI involved** —
python-docx opens the template as the base document and writes content using its
named styles (`Title`, `Heading 1`, `Body Text`, `Caption`), falling back to
`Normal` for any the template lacks.

You can upload a filled-in past report, not just a blank template: the body
content is stripped while styles, section setup and the letterhead are kept.

A missing or corrupt template never blocks a report — it logs and falls back to
the plain format.

| Route | Does |
|---|---|
| `GET /api/template` | the app-wide record, or null (no project needed) |
| `POST /api/template` | multipart `template` (.docx only); replaces it for every report |
| `DELETE /api/template` | every report reverts to plain formatting |

## Data model

```
Item   001                     a numbering group only
  └ Photo 001_01   THE INCIDENT: photo? · description · location ·
  │                importance · tags · include · audio_clips[]
  └ Photo 001_02
  └ Audio 001_01_A01
Item   002
```

999 items x 99 photos per item. **The incident is the photo entry, not the
item** - an item is just a container. A photo entry may have no image yet
(`filename: null`), so a voice note or a plan pin can be recorded before the
picture is taken; the export skips the image for those.

Photo IDs are scoped to their item, so `I-001-P-02` identifies both at once —
useful when embedding the ID into the photo and when placing it in the report.

`location` is `{plan_id, page, x, y}` where **x and y are normalized 0.0–1.0
fractions, never pixels**. A marker placed on a phone then renders correctly at
any other size in the Word report.

## Voice to text

Two independent paths, so the app never depends on a paid key:

1. **Dictate** (primary) — Web Speech API, runs in the browser, **free, no key**.
   Works in Chrome/Android and Safari/iOS 14.5+. Live interim text appears as you
   speak; only finalized text is persisted. Needs HTTPS, which the tunnel provides.
2. **Record audio** (optional) — uploads and **keeps** the clip on the server.
   A per-item checkbox decides whether it is also transcribed:
   - unchecked (default) → audio is stored and nothing is sent anywhere
   - checked → Whisper transcribes it, if `OPENAI_API_KEY` is set
     (~$0.006/min, noticeably better on structural jargon)

   Every recording is kept — `I-001-A-01`, `I-001-A-02`, … — playable inline and
   individually deletable. Useful when you would rather re-listen on site than
   trust a transcript.

If neither is available, the phone keyboard's own mic key dictates into the
description box with no code at all.

## Adding a photo

`POST /api/item/<id>/photo` with `inherit`:

- `keep` - copies `description`, `location`, `importance` and `tags` from the
  previous entry. The photo and the audio are never copied.
- `clear` (or `new`) - a blank entry.

An upload should send `photo_id` naming the entry it belongs to. Without it the
server picks the **newest** imageless entry.

## Severity

`Info · Minor · Major · Critical · Safety` — from the Summary slide.

## API

| Route | Does |
|---|---|
| `GET /api/visit` | all items + plans |
| `POST /api/item` | new item |
| `PATCH /api/item/<id>` | nothing editable (the fields moved to the entry) |
| `DELETE /api/item/<id>` | remove item + its uploads |
| `POST /api/item/<id>/photo` | multipart `photo` (+ `photo_id` to name the target entry), or `inherit=keep\|clear` to add an entry |
| `PATCH /api/item/<id>/photo/<pid>` | `caption, description, action, importance, tags, include, location` |
| `DELETE /api/item/<id>/photo/<pid>` | remove the entry and its files |
| `POST /api/item/<id>/photo/<pid>/audio` | multipart `audio` + `transcribe=true\|false` |
| `DELETE /api/item/<id>/photo/<pid>/audio/<clip_id>` | remove one recording |
| `POST /api/plan` | multipart `plan` (pdf/image) |
| `GET /api/export/docx` | Word report of **included** items only |
| `GET /health` | public, no PIN |

### Reports

| Route | Does |
|---|---|
| `GET /` | landing page |
| `GET /capture` | the capture UI (302 to `/` if no report is open) |
| `GET /api/jobs` | every project, sorted by number |
| `POST /api/jobs` | create: `name`, `number`, `address` |
| `GET /api/jobs/<jid>` | project, visits, action items, next visit defaults |
| `PATCH` / `DELETE /api/jobs/<jid>` | edit / delete with all its visits |
| `POST /api/jobs/<jid>/visits` | new visit (opens it) |
| `GET` / `PATCH /api/visits/<pid>` | a visit's info |
| `GET /api/visits/current` | the open visit and its project |
| `POST /api/visits/<pid>/entries/<photo_id>/updates` | `date, text, visit_no, close` |
| `DELETE /api/visits/<pid>/entries/<photo_id>/updates/<n>` | remove one (the final one reopens) |
| `POST /api/visits/<pid>/entries/<photo_id>/reopen` | undo a close-out |
| `GET /api/projects` | all visits + `current` |
| `POST /api/projects` | a project of that name with Site Visit 1 |
| `POST /api/projects/<pid>/open` | open a visit for this session |
| `DELETE /api/projects/<pid>` | delete a visit and all its files |
| `POST /api/projects/close` | close without opening another |

Data routes return **409 `no project open`** when none is selected; the UI
redirects to `/` on a 409.

## Config

| Env var | Default |
|---|---|
| `SITESCRIBE_PIN` | `2424` |
| `SITESCRIBE_SECRET` | random per start |
| `OPENAI_API_KEY` | optional. Unset → the **Dictate** button still works (browser speech recognition, free); only the server-side Whisper transcription of recorded audio is skipped |

**Never commit a key.** Put it in a `.env` on the server only.

## Notes

- `data/visit.json` writes are atomic (temp + rename) — an interrupted save
  cannot corrupt the visit.
- Transcription runs outside the write lock, so a slow Whisper call does not
  block other requests.
- Uploads are `secure_filename`'d and prefixed with the photo id.
