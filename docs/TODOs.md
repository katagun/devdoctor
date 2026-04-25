# diskdoctor — UI/UX TODOs

Issues found during scan-view review on 2026-04-25. All landed in the
same pass.

## P0 — correctness

- [x] **Cursor cache mislabeled as `vscode-cache`.** Split into a dedicated `cursor-cache` provider in `paths.yaml` with its own description and recipe. Added `siCursor` icon mapping so the row no longer borrows the VS Code mark.
- [x] **"X reclaimable" headline double-counted DANGER rows.** `useScan.ts` now filters `risk === "dangerous"` out of `totalBytes`, so the headline matches the taxonomy.

## P1 — UX correctness

- [x] **OWNER and PERMS shown by default.** Marked `defaultVisible: false` on both columns; new `DEFAULT_HIDDEN_COLUMNS` constant feeds the settings default. Default order is now PROVIDER → SIZE → RISK → STALE; OWNER/PERMS stay one click away in the columns picker.
- [x] **`clean up` button looked active when 0 selected.** Replaced `disabled:opacity-50` over a bright gradient with a flat dim background + neutral border + muted text when nothing is selected.

## P2 — polish

- [x] **Missing provider icons.** Added local-bundled monochrome glyphs for `slack`, `playwright`, `lm-studio`, and `downloads` (all four removed from / never added to simple-icons).
- [x] **`ollama` row shape.** Logical entries (path=null) no longer render `—` in owner/perms — those columns are deliberately blank when the row has no filesystem path. `—` is reserved for path-backed rows where stat actually failed.
- [x] **"+N under threshold" buried in footer.** The footnote is now a button with caret; clicking expands the table to include the hidden small caches and updates the totals to match.
