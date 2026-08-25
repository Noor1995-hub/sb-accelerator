# Inbox

The landing zone for anything not yet processed into a vault object: meeting
transcripts, voice memos, forwarded emails, recorder exports, documents to file.

Rules:

- **Everything unprocessed lands here first.** Drop files in; don't sort them.
- **What is in this folder is what still needs processing.** The sync moves
  every file it handles out to `90-archive/inbox/{YYYY-MM}/` — whether it
  became a note or was parked as not-a-capture. So the folder answers "what
  is still outstanding?" by itself, without running anything.
- **Processing produces notes in `20-meetings/`.** A recording of an
  interaction becomes a meeting note. Something that carries context but is
  not a meeting — a forwarded email, a voice memo — becomes a note with
  `type: note`. Both land in the same triage queue, `Meetings.base`.
- **Anything that is not a capture is parked**, not filed. A whitepaper or a
  deck goes to the archive with a short note beside it saying why it was
  parked and how to have it processed after all; the sync does not decide
  where your reference material belongs.
- Skills never leave their outputs in this folder.
