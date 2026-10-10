# ADR-0006: SourceUnits split at page boundaries; turn grouping

**Context.** The citation contract has one `page` and `line_start ≤ line_end`. A speech turn can cross a page break.

**Decision.** A turn that spans pages becomes one SourceUnit per page; all parts share `turn_key` and carry `turn_part`. Citations point to the exact page part; the citation endpoint returns the continuation parts so a reader sees the whole turn. Q/A pairing uses the first part of each turn and the full turn text.

**Line numbers.** Printed margin numbers are preserved as the original line numbers. Pages without printed numbers (or OCR pages) get synthetic numbers and `synthetic_lines=true`, which the UI states explicitly.
