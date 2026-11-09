# Canny to Notion sync

I built this because Canny feedback and a Notion roadmap drift apart. The Notion request on Canny's Integrations board has 258 votes and has been Under Review since August 2019. I think most people asking for it want the same thing: their posts in a Notion database, next to their specs and roadmap, without copying them by hand. This keeps one Notion row per Canny post and updates it when the post changes.

## What it does

It is a one way sync of Canny posts into a Notion data source. Each row gets the title, details, status, vote score, board, category, tags, author, created time, status changed time, and the post link.

1. `setup` adds the properties the sync needs to a Notion database you already created, or only checks them with `--check`. It does not create the database.
2. `backfill` reads every post through the Canny API, page by page, and creates or updates one Notion row per post. Running it twice writes nothing the second time.
3. `serve` runs a small webhook receiver. It checks the Canny signature (Standard Webhooks: HMAC SHA256 over `{id}.{timestamp}.{raw body}`, base64, in `webhook-signature`) and updates the matching row on `post.created`, `post.status_changed`, `vote.created`, `vote.deleted`, and `post.deleted`.
4. `demo` runs all of the above on fake data, with no keys.

A few choices, and why:

* **The row is keyed by the Canny post ID**, in a text property called `Canny ID`. Titles change and URLs can change, but the ID doesn't.
* **It only writes when something changed.** It reads the row back and compares first. Notion rate limits are low, and I think a quiet sync is easier to trust.
* **Canny posts have no general `updatedAt`.** Change detection compares every mapped field (title, details, status, score, board, category, tags, author, dates, URL). The `statusChangedAt` value is stored as a date and compared to the minute, because Notion rounds date properties that way.
* **On every webhook it reads the current post from the API**, instead of trusting the event body. Vote events don't carry the score. One extra retrieve is cheap and the row always ends up with the latest state.
* **Status, Board, and Category are Select properties.** Notion adds a new Select option by itself when a post uses a value it hasn't seen. Tags use Multi select.
* **A deleted post keeps its row**, with the status set to `Deleted in Canny`. Deleting things in someone's Notion felt like the wrong default.
* **The title property keeps its name.** The tool finds it by type, so an existing database called "Request" or "Name" both work.
* **It never changes a property type.** If `Votes` already exists as text, `setup` stops and says so, because changing a type can lose data.
* **Standard library only.** There is nothing to install to run it. Pytest is the only dependency, it is pinned, and it is only for the tests.

## Setup

You need Python 3.10 or newer.

1. Create a free Canny account at [canny.io](https://canny.io). The Free plan includes the API and webhooks, and it does not ask for a card. Confirm on their [pricing page](https://canny.io/pricing) if that ever changes.
2. In Canny, open Settings, then API & Webhooks, and copy your secret API key.
3. Create a few posts on a board with different statuses so the sync has something real to copy.
4. In Notion, go to [integrations](https://www.notion.so/profile/integrations), create an internal integration, and copy its token.
5. Create an empty full page database in Notion (an empty Table is fine).
6. Click the ••• menu at the top right, then Connections, and add your integration.
7. Click Share, then Copy link. The URL looks like `https://www.notion.so/yourworkspace/Something-1a2b3c4d5e6f47a8b9c0d1e2f3a4b5c6?v=...`. The database ID is the 32 characters after the last dash and before `?v=`. Leave out the `?v=` part.
8. Set the env vars and run setup, then the backfill:

```
export CANNY_API_KEY=...
export NOTION_TOKEN=...
export NOTION_DATABASE_ID=...
python3 sync.py setup
python3 sync.py backfill
```

Optional: set `CANNY_BOARD_ID` to sync only one board.

For live updates, run the receiver somewhere with a public https URL, and register `https://your.host/webhooks/canny` in Canny under Settings, API & Webhooks. Copy the signing secret (`whsec_...`):

```
export CANNY_WEBHOOK_SECRET=whsec_...
python3 sync.py serve --port 8080
```

If the Notion database has more than one data source, set `NOTION_DATA_SOURCE_ID` too. The tool never prints any of these values.

## Demo run

```
python3 sync.py demo
```

It uses 20 fake posts in `samples/`, a fake Canny API and a fake Notion database in memory. The webhook part goes through the real HTTP server on 127.0.0.1, with events signed the way Canny signs them (Standard Webhooks). Nothing leaves the machine. Trimmed output:

```
== 2. backfill (20 posts, Canny pages of 10)
  created   post_00_notion  'Notion'
  ...
  20 created, 0 updated, 0 unchanged, read in 2 Canny pages

== 3. backfill again, nothing should change
  0 created, 0 updated, 20 unchanged, Notion writes: 0

== 4. webhooks through the real HTTP server on 127.0.0.1
  created   post_new_two-way-notion  'Two way sync with Notion databases'  (post.created)
  updated   post_00_notion  'Notion'  status: 'under review' -> 'in progress', ...  (post.status_changed)
  updated   post_00_notion  'Notion'  votes: 258 -> 259  (vote.created)
  duplicate msg_demo_0003, skipped
  updated   post_05_csv-export-of-votes  (post.deleted, row kept and marked)
  -> wrong secret: HTTP 401
  -> 10 minute old timestamp: HTTP 401
```

All posts are made up except the Notion one, which mirrors the public request. To rebuild the samples, run `python3 samples/generate.py`.

To run the tests:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

The tests mock every HTTP call. They cover paging, the mapping, idempotent upserts, valid and invalid signatures, and each event type. One test starts the receiver on 127.0.0.1 and sends it signed requests.

## Assumptions

I read the Canny API reference (auth, boards/list, posts/list, posts/retrieve), the help article on the API and webhooks, and the Notion API reference. Where the docs didn't say, I made a choice and wrote it here.

From the docs:

* Canny: base URL `https://canny.io`, every call is POST with JSON, auth is `apiKey` in the body, `POST /api/v1/posts/list` with `skip` and `limit` until `hasMore` is false, `POST /api/v1/posts/retrieve` with `id`, `POST /api/v1/boards/list`. Post fields: `id`, `title`, `details`, `status` (string), `score`, `board.name`, `category.name`, `tags[].name`, `author.name`, `created`, `statusChangedAt`, `url`.
* Webhooks: Standard Webhooks. Headers `webhook-id`, `webhook-timestamp`, `webhook-signature`. Secret starts with `whsec_`. Signed content is `{id}.{timestamp}.{raw body}`, HMAC SHA256, base64, entries like `v1,<sig>`. Rejected after 5 minutes. Event envelope fields `type`, `object`, `objectType`, `created`. Topics used here: `post.created`, `post.status_changed`, `post.deleted`, `vote.created`, `vote.deleted`.
* Notion: API version `2026-03-11`, the database to data source model, `GET /v1/databases/{id}` for the data source, `GET` and `PATCH /v1/data_sources/{id}` for the schema, `POST /v1/data_sources/{id}/query` with a `rich_text` `equals` filter and `start_cursor`, `POST /v1/pages` with a `data_source_id` parent, `PATCH /v1/pages/{id}`. 2000 characters max for text and URLs, no commas in Select options. Date properties round to the minute.

My assumptions:

1. **No post `updatedAt`.** The documented post object has `created` and `statusChangedAt`, not a general last updated time. I detect changes by comparing every mapped field. A field Canny changes without touching those dates (for example only the score) still shows up on the next backfill or vote webhook.
2. **Vote event shape.** The help center lists `vote.created` and `vote.deleted`. The object may carry `postID` or a nested `post`. I accept both, then retrieve the post.
3. **Webhook object for posts.** I treat `object` as the post (or a partial post with `id`) for post topics, matching the help center examples and common Canny payloads.
4. **Empty Select when adding a property.** I send `{"select": {}}` to add a Select with no options yet. The docs show option lists, not the empty case.
5. **Commas in names.** A status, board, category, or tag name with a comma gets the comma replaced by a space, because Notion rejects commas in options.
6. **Duplicate deliveries.** I remember the last 10,000 `webhook-id` values in memory. After a restart a duplicate gets through, but the upsert is idempotent, so it only costs a read.

## Limits

* This is not affiliated with Canny or Notion. It is a small helper I wrote from their public API docs.
* The demo and the tests run against fakes built from the docs. I have not tested this against a live Canny workspace or a live Notion database in this repository. If you do, a second `backfill` should report every row unchanged.
* It is one way, Canny to Notion. Edits made in Notion to the synced columns get overwritten on the next change. Other columns you add are left alone.
* The Free plan includes API and webhooks per Canny's docs. Rate limits on Free are lower (5 requests per second, 100 per minute, 1,000 per hour), so a large board should use a moderate page size.
* The receiver answers 200 first and writes to Notion after. If a Notion write fails, the event is not retried, so a periodic backfill is the safety net.
* Notion queries return at most 10,000 rows. The backfill index would miss rows beyond that, so a very large board needs a different index.
* Comments, custom fields, ETA, and Jira or Linear links aren't synced yet. They are easy to add to the mapping once someone says which ones matter.
