# Decisions

Running log of assumptions and trade-offs not already settled by `spec.md` or `CLAUDE.md`.

- 2026-07-27 — The sheet reproduces the reference form's black hour-band masthead, remarks bar and recap strip. Recap fields A/B/C stay blank printed fields because the API's scalar cycle figure cannot reconstruct an 8-day history; "on duty today" is filled since it is by definition the sum of lines 3 and 4. App-level cycle arithmetic stays in the trip summary.
- 2026-07-27 — Sheet "From / To" fields take the day's first and last remark locations; a day spent wholly inside a rest prints them blank, as the paper form would.
- 2026-07-27 — The empty state renders a complete blank RODS (header fields, grid, shipping block, recap) from the same shared components as the filled sheet, so the two cannot drift apart visually.
