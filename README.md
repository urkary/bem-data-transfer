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
2. **OTP card** — select the `.bin` dump of the card whose OTP the physical card has
3. The output filename is suggested automatically; change it if you want
4. Click **Transfer**
5. Flash the resulting `.bin` onto the physical card using an SPI flash programmer (e.g. CH341 or CH347 with AsProgrammer)

---

## Compatibility

- Vital Bracelet BE BEM cards (4 MB `.bin` dumps)
- Tested combinations:
  - Demon Slayer DS01 data → DS02 DIM physical card
  - My Hero Academia MHA01 data → Tokyo Revengers TR01 physical card

---

## For developers — run from source

**Requirements:** Python 3.9 or newer. Tkinter is included with standard Python installations.

```bash
python3 bem_transfer.py
```

> **Note on WSL2:** The window may look unstyled when running under WSL2 due to X11 forwarding. Run natively on Windows/macOS/Linux for the best appearance.

### Build a standalone executable

```bash
pip install pyinstaller
pyinstaller --onefile bem_transfer.py
```

The executable will be at `dist/bem_transfer` (Linux/macOS) or `dist/bem_transfer.exe` (Windows).

