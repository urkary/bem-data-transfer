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

## Compatibility

- Tested combinations:
  - Demon Slayer DS01 data → DS02 DIM physical card
  - My Hero Academia MHA01 data → Tokyo Revengers TR01 physical card

