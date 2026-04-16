# BEM Data Transfer

Combines the content of two Vital Bracelet BEM card dumps into a single `.bin` file ready to flash onto a physical card.

---

## For end users — download and run

### Windows

1. Go to the [Releases](../../releases) page and download `BEM-data-transfer-windows.exe`
2. Double-click it — no installation required

### macOS

1. Download `BEM-data-transfer-macos` from [Releases](../../releases)
2. Open a Terminal, run:
   ```
   chmod +x BEM-data-transfer-macos
   ./BEM-data-transfer-macos
   ```

### Linux

1. Download `BEM-data-transfer-linux` from [Releases](../../releases)
2. In a terminal:
   ```
   chmod +x BEM-data-transfer-linux
   ./BEM-data-transfer-linux
   ```

---

## Usage

1. **Data card** — select the `.bin` dump of the card whose content (characters, sprites, adventures) you want to use
2. **Target physical card** — select the `.bin` dump of the target physical card
3. The output filename is suggested automatically; change it if you want
4. Click **Transfer**
5. Flash the resulting `.bin` onto the physical card using an SPI flash programmer (e.g. CH341 or CH347 with AsProgrammer)

---

## Command-line usage

When running from source (`python bem_transfer.py`) or from a terminal, you can pass subcommands instead of opening the GUI.

### Transfer

```
python bem_transfer.py transfer --data_card <file> --target_card <file> [--output_card <file>]
```

- `--data_card` — card whose content (sprites, characters…) you want to use
- `--target_card` — target physical card that provides the OTP signatures
- `--output_card` — output path (optional; auto-generated next to the data card if omitted)

### Card info

```
python bem_transfer.py info --card <file>
```

Prints card name, dimId, and sprite count.

### Capacity check

```
python bem_transfer.py check <file> [file …]
```

Dry-runs the sprite placement for one or more cards and reports how much space
is used and how much margin is left. Useful for verifying that all sprites fit
correctly when accounting for checksum corrector placement. Exits with code 1
if any card overflows.

Example — check all cards in a folder:

```
python bem_transfer.py check path/to/cards/*.bin
```

---

## Compatibility

- Tested combinations:
  - Demon Slayer DS01 data → DS02 DIM physical card
  - My Hero Academia MHA01 data → Tokyo Revengers TR01 physical card

