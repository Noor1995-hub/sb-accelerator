# Plaud direct-fetch spike — CLI-side Plaud transcript fetch (lever 6)

**Date:** 2026-09-17
**Status:** spike in progress — Cowork parity is the gate
**Related:** the 2026-09-17 sync-cost-round-4 plan (PR D), memory
`cowork-provisioning-constraints`, issue #133 ("ideas for Claude Code
deployments").

## Why

Lever 6 of the 2026-09-17 cost analysis: fetch the raw Plaud transcript
directly from a CLI-side script instead of round-tripping through the
Plaud MCP tools and the orchestrator's context. It only pays for itself if
it works identically in both deployment surfaces the vault runs in — a
Claude Code host checkout and a Cowork VM session. Cowork parity is a hard
requirement, decided with Michael on 2026-09-17: if the spike shows Cowork
can't do it, this is a documented no-go, not a Claude-Code-only feature.

## Facts established (read-only, 2026-09-17)

- The host-side `@plaud-ai/mcp` 0.3.13 is a real MCP server: it calls
  `https://platform.plaud.ai/developer/api/open/third-party/files/{fileId}`
  (whole transcript per recording; `get_transcript` paginates *locally*)
  and `/open/third-party/users/current`, `Authorization: Bearer` from
  `~/.plaud/tokens-mcp.json` (`access_token`, `refresh_token`,
  `expires_at`), refresh = POST form `refresh_token=` to
  `…/oauth/third-party/access-token/refresh`; its OAuth client id is
  Plaud's own MCP client.
- Plaud's support page states there is **no public API**; the developer
  platform ("Plaud Embedded") is a partner transcription API for audio you
  upload, not an account-data API.
- Cowork's Plaud connector is the remote `https://mcp.plaud.ai/mcp` (OAuth
  held by the connector platform) — the VM has no token file; the sandbox
  egress allowlists package hosts only (memory
  `cowork-provisioning-constraints`).
- (Found while building the probe, not in the original brief:) a live
  `~/.plaud/tokens-mcp.json` on this Mac stores `expires_at` as epoch
  **milliseconds** (a 13-digit int), not seconds — worth knowing if anyone
  hand-parses this file elsewhere.
- (Found on the live Claude Code host run:) `platform.plaud.ai` sits
  behind Cloudflare, which returns **403 "error 1010 — browser signature
  banned"** for the default `Python-urllib/3.x` User-Agent, on every
  route, with the token otherwise perfectly valid. A non-Python UA (the
  Node MCP itself sends `undici`) clears every route.

## The three gates

The spike is a go only if all three hold. Fail any one → **no-go**.

1. **(a) Egress** — the Cowork VM can reach `platform.plaud.ai` at all.
   The sandbox's package-host allowlist (memory
   `cowork-provisioning-constraints`) is the known failure mode; expected
   result is a 403 on CONNECT or a probe-level connection error.
2. **(b) A distinct credential** — a credential exists inside Cowork that
   is *not* the MCP server's own rotating token. Sharing one
   refresh-rotating token between two independent clients breaks the MCP
   the moment either side rotates it out from under the other — so
   "Cowork happens to have the same token file" does not satisfy this
   gate, it fails it.
3. **(c) Sanction** — Plaud sanctions this API for third-party use. The
   support page's "no public API" statement is evidence against this, not
   for it — treat it as a no-go on this gate unless directly resolved
   with Plaud. Plaud's own edge actively bans non-browser client
   signatures (Cloudflare error 1010 for the default `Python-urllib` UA) —
   further evidence that unlisted clients are not welcome, consistent
   with the "no public API" statement.

## Method

`scripts/spikes/plaud_direct_fetch_probe.py` — read-only GETs/HEADs only,
never calls the refresh endpoint, never writes anything, never prints or
logs token bytes (not even a prefix). It reports: token-file presence,
which expected keys it has, and `expires_at`/expired; per-host egress
(`HEAD /health`); `GET users/current` status plus an `id`-presence
boolean; `GET files/{id}` status, byte size, and top-level JSON keys; and,
with `--compare`, whether the MCP's own scratch-page utterance sequence
matches the direct API response's utterances (a `source_list[]` entry
with `data_type == "transaction"`, whose `data_content` JSON string holds
the transcript the MCP itself parses).

Two runs, by two different operators — the Cowork run needs a human at
the Cowork UI; no Claude Code session can open Cowork itself:

1. **Claude Code host run** — this Mac, a DryRunVault recording id, run
   after go-ahead (uses a real, existing access token; read-only, no
   refresh).
2. **Cowork VM run** — inside a Cowork session on the DryRunVault folder,
   run by Michael. Expected, per the facts above: no token file present,
   egress fails (403 on CONNECT or a connection-error class from the
   probe).

## Results

### Claude Code host run

- [x] `token_file.present`: **true** — keys `access_token`,
      `refresh_token`, `expires_at`; `expires_at` is epoch
      **milliseconds**; **not expired**.
- [x] `egress[]`: `platform.plaud.ai` → **403** (Cloudflare error 1010,
      "browser signature banned") with the default Python-urllib
      User-Agent; **404** with a non-Python User-Agent — reachable (no
      such route, not a block). `mcp.plaud.ai` → `/health` **200**.
- [x] `users_current.status` / `has_id`: **403** (Cloudflare 1010) with
      the Python UA; **200** with a non-Python UA. Response top-level
      keys: `avatar`, `email`, `id`, `member_id`, `nickname`,
      `workspace_id`.
- [x] `file.status` / `size_bytes` / `top_level_keys`: recording
      `of_de01a3bd6a5aed9b81d31af60758c080` (a DryRunVault meeting synced
      2026-09-17) → **200**, **123800 bytes**; top-level keys
      `created_at`, `duration`, `id`, `name`, `note_list`,
      `presigned_url`, `serial_number`, `source_list`, `start_at`.
      `source_list` entries: `transaction` (`data_content` 81538 chars —
      a JSON string of 259 utterances, keys `content`, `end_time`,
      `original_speaker`, `speaker`, `start_time`), `transaction_polish`
      (empty, `data_link` only), `outline` (3856 chars). `note_list`:
      `auto_sum_note` (23551 chars, `data_error_code` 10). One `GET`
      returns the whole transcript the MCP otherwise serves across six
      paginated pages.
- [ ] `compare.match` / `mcp_count` / `api_count` — **not run**: the MCP
      scratch pages from that sync had already been swept before this
      probe ran.

### Cowork VM run

- [ ] `token_file.present`
- [ ] `token_file.keys_present`
- [ ] `token_file.expires_at` / `expired`
- [ ] `egress[]` status or error per host (`platform.plaud.ai`,
      `mcp.plaud.ai`)
- [ ] `users_current.status` / `has_id`
- [ ] `file.status` / `size_bytes` / `top_level_keys`
- [ ] `compare.match` / `mcp_count` / `api_count` (if `--compare` used)

## Decision

_Pending both runs. Go only if gates (a), (b), and (c) all hold;
otherwise no-go, recorded here, with the Claude-Code-only variant noted
under issue #133's "ideas for Claude Code deployments" and no plugin
change._
