# Changelog

## [0.2.0] — 2026-04-16

### Fixed
- **Corrupt pixels in transferred cards.** v0.1.0 always placed the 2-byte
  checksum corrector at bytes 0–1 of each chunk's checksum area, which
  overwrote one RGB565 pixel per active chunk (up to 34 corrupted pixels in
  a DS02 card). The corrector is now placed in the nearest free gap using a
  pool-based sprite placement algorithm (`place_sprites`), guaranteeing it
  never overlaps pixel data. Validated on DS02→DS01: all checksums correct,
  376 sprites pixel-identical to the original.

### Added
- **Command-line interface.** `bem_transfer.py` can now be invoked with
  arguments for scripting and batch use. Without arguments it still opens the
  GUI as before. Subcommands:
  - `transfer --data_card <file> --target_card <file> [--output_card <file>]`
    — performs the transfer from the command line.
  - `info --card <file>` — prints card name, dimId, and sprite count.
  - `check <file> [file …]` — dry-runs the sprite placement for one or more
    cards and reports bytes used, capacity, and margin. Exits with code 1 if
    any card overflows or cannot be read.

## [0.1.0] — 2024-01-01

Initial release.
