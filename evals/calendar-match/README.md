# calendar-match evals

Real recordings replayed against real calendar shapes, with the outcome a
human judged right. They are not CI tests. Run them when you change
`m365.calendar_match` or step 2 of `/sync-recordings`, and say in the PR
what moved:

```bash
python3 scripts/eval_calendar_match.py
```

Each case file holds `listings` (one `outlook_calendar_search` result per
day, shaped like the connector's output) and `recordings`. Each recording
names the CLI answer it should get (`expect_cli`) and the final outcome
(`expect_final`):

| `expect_final` | means | what the runner checks |
|---|---|---|
| `time` | matched on the clock alone | `single` on `expect_event` |
| `content` | the model picks it from the candidates on title or agenda | `expect_event` is among the candidates |
| `side-call` | unmatched, debrief says it was recorded during a meeting | an attended candidate contains the recording |
| `none` | unmatched, nothing to say | no attended candidate contains it |

The `content` cases depend on model judgment, so the runner only checks
the half the CLI owns: that the right event reaches the model.

**Anonymise before you commit.** Times, `showAs`, organizer and attendee
counts are kept as recorded. Subjects, titles and addresses are rewritten:
no client or person names, as for `plugin/`.

- `replay-2026-10-12.json`: 19 recorder recordings (2026-10-12..14) that
  the matcher in 0.13.22 left unmatched. 8 were misses. The 0.13.25 fix
  takes them from 8/19 to 19/19.
