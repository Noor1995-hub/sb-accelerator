## Inbox Discipline

Unprocessed capture lands in `10-inbox/` and only there. Processing skills
consume from the inbox and write results to the proper object folders. Skill
outputs never land in the inbox.

Processing also empties it: every file the sync handles moves to
`90-archive/inbox/{YYYY-MM}/`, so what remains in `10-inbox/` is exactly
what is still outstanding. A capture that is not a meeting — a forwarded
email, a voice memo — becomes a note with `type: note` in `20-meetings/`,
sharing the one triage queue rather than starting a second one. Anything
that is not a capture at all is parked to the archive rather than filed,
because deciding where reference material belongs is yours, not the
sync's.
