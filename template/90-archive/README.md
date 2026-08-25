# Archive

Completed and historical items. Nothing reads from here — it exists so that
nothing has to be deleted.

`inbox/{YYYY-MM}/` is written by the sync: every file it processed into a
note, and every file it parked as not-a-capture, moved out of `10-inbox/` so
that folder holds only what is still pending. The original bytes are
untouched, so a file here can always be dropped back into `10-inbox/` if
something needs redoing — though a note that was already written will keep
it deduped, so delete that meeting note in `20-meetings/` first. It is the
note that gets deleted, never the archived file itself.
