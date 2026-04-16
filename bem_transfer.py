"""
BEM Data Transfer
Transfers the content of one Vital Bracelet BEM card into the OTP shell of another,
allowing cards to be used on physical cards with a different OTP.
"""

import logging
import os
import struct
import tkinter as tk
from tkinter import filedialog, messagebox

# ── Binary layout constants ────────────────────────────────────────────────────
HEADER_SIZE            = 0x1030
SPRITE_PACKAGE_START   = 0x100000
CHECKSUM_LOCATION      = 0x3FFFFE
NUM_CHUNKS             = 48          # 0x30 chunks in BEM sprite package
CHUNK_SIZE             = 0x10000
CHECKSUM_AREA_OFFSET   = 0x2000     # relative to sprite package start, per chunk
CHECKSUM_AREA_SIZE     = 0x1000     # 4 KB per chunk
PTR_TABLE_OFFSET       = 0x4C       # offset of pointer table within sprite package
DIM_SECTION            = 0x060000   # sprite dimensions table (w, h pairs)
SPRITE_PKG_END         = SPRITE_PACKAGE_START + NUM_CHUNKS * CHUNK_SIZE  # 0x400000
GLOBAL_SKIP            = {0x10000, 0x10002, 0x10004, 0x10006, CHECKSUM_LOCATION}
EXPECTED_SIZE          = 0x400000   # 4 MB

# ── Core binary logic ──────────────────────────────────────────────────────────

def read_bin(path: str) -> bytearray:
    data = bytearray(open(path, "rb").read())
    if len(data) != EXPECTED_SIZE:
        raise ValueError(f"Tamaño inesperado: {len(data):#x} (se esperan {EXPECTED_SIZE:#x} bytes)")
    return data

def logical_u16(raw: bytearray, offset: int) -> int:
    """Read a uint16 LE from disk bytes and return its logical (un-NOT'd) value."""
    return struct.unpack_from("<H", raw, offset)[0] ^ 0xFFFF

def logical_u32(raw: bytearray, offset: int) -> int:
    """Read a uint32 LE from disk bytes and return its logical (un-NOT'd) value."""
    return struct.unpack_from("<I", raw, offset)[0] ^ 0xFFFFFFFF

def card_name(data: bytearray) -> str:
    return bytes(b ^ 0xFF for b in data[0x10:0x30]).decode("ascii", errors="replace").rstrip()

def dim_id(data: bytearray) -> int:
    return data[0x32] ^ 0xFF

def chunk_checksums(data: bytearray) -> list[int]:
    """Compute the 48 logical chunk checksum values from the sprite package."""
    result = []
    for n in range(NUM_CHUNKS):
        area = SPRITE_PACKAGE_START + n * CHUNK_SIZE + CHECKSUM_AREA_OFFSET
        total = 0
        for i in range(0, CHECKSUM_AREA_SIZE, 2):
            total = (total + logical_u16(data, area + i)) & 0xFFFF
        result.append(total)
    return result

def read_sprite_metadata(data: bytearray) -> tuple:
    """Read n_sprites, pointer table, and dimensions from the sprite package."""
    pkg = SPRITE_PACKAGE_START
    n = logical_u32(data, pkg + 0x48)
    ptrs = [logical_u32(data, pkg + PTR_TABLE_OFFSET + i * 4) for i in range(n)]
    dims = []
    off = DIM_SECTION
    for _ in range(n):
        w = logical_u16(data, off)
        h = logical_u16(data, off + 2)
        dims.append((w, h))
        off += 4
    return n, ptrs, dims

def extract_sprites(data: bytearray, n: int, ptrs: list, dims: list) -> list:
    """Extract pixel data for all sprites; returns list of (original_idx, size, pixels)."""
    pkg = SPRITE_PACKAGE_START
    sprites = []
    for i in range(n):
        abs_ptr = pkg + ptrs[i]
        w, h = dims[i]
        size = w * h * 2
        sprites.append((i, size, bytes(data[abs_ptr:abs_ptr + size])))
    return sprites

def place_sprites(output: bytearray, sprites: list, n_sprites: int) -> tuple:
    """
    Place sprites in the output, choosing positions so the 2-byte corrector for each
    chunk's checksum area never overlaps with sprite pixel data.

    Pool selection rules (smallest fitting sprite wins in every case):
      Rama A  (write_pos >= area_end):   write smallest sprite
      Rama B  (write_pos inside area):   write smallest that fits before area_end;
                                         if none fits, skip to area_end
      Rama C  (write_pos < area_start, corrector not yet placed):
        Case i  — smallest where end lands inside [area_start, area_end):
                  write it, place corrector just after it, advance by size+2
        Case ii — smallest that fits entirely before area_start: write it, advance
        Case iii— all sprites overflow area_end: place corrector at bytes 0-1 (default),
                  jump write_pos to area_start+2

    Returns (new_ptrs, corrector_pos, end_ptr).
    """
    pkg = SPRITE_PACKAGE_START
    pool = sorted(sprites, key=lambda s: s[1])   # ascending by size

    write_pos = pkg + PTR_TABLE_OFFSET + (n_sprites + 1) * 4
    new_ptrs = [0] * n_sprites
    # Default corrector position: bytes 0-1 of each area
    corrector_pos = [pkg + c * CHUNK_SIZE + CHECKSUM_AREA_OFFSET for c in range(NUM_CHUNKS)]
    corrector_set = [False] * NUM_CHUNKS

    def _check_overflow(idx: int, size: int) -> None:
        if write_pos + size > SPRITE_PKG_END:
            data_start = pkg + PTR_TABLE_OFFSET + (n_sprites + 1) * 4
            logging.error(
                "Sprite overflow: sprite %d (size=%d) at write_pos=0x%X "
                "would exceed sprite package end 0x%X "
                "(used=%d bytes, capacity=%d bytes)",
                idx, size, write_pos, SPRITE_PKG_END,
                write_pos - data_start,
                SPRITE_PKG_END - data_start,
            )
            raise ValueError(f"Sprite data overflow at sprite {idx}")

    while pool:
        rel = write_pos - pkg
        chunk_idx = rel // CHUNK_SIZE

        if chunk_idx >= NUM_CHUNKS:
            idx, size, _ = pool[0]
            data_start = pkg + PTR_TABLE_OFFSET + (n_sprites + 1) * 4
            logging.error(
                "Sprite overflow: sprite %d still unplaced, write_pos=0x%X exceeds "
                "sprite package (used=%d bytes, capacity=%d bytes)",
                idx, write_pos, write_pos - data_start, SPRITE_PKG_END - data_start,
            )
            raise ValueError(f"Sprite data overflow: write_pos=0x{write_pos:X}")

        area_start = pkg + chunk_idx * CHUNK_SIZE + CHECKSUM_AREA_OFFSET
        area_end   = area_start + CHECKSUM_AREA_SIZE

        if write_pos >= area_end:
            # ── Rama A ──────────────────────────────────────────────────────────
            # Before writing, check prospectively for the next chunk's area:
            # a sprite written here may span into it, causing corrector overlap.
            next_chunk_idx = chunk_idx + 1
            if next_chunk_idx < NUM_CHUNKS and not corrector_set[next_chunk_idx]:
                next_area_start = pkg + next_chunk_idx * CHUNK_SIZE + CHECKSUM_AREA_OFFSET
                next_area_end   = next_area_start + CHECKSUM_AREA_SIZE

                # Case i: smallest crossing next_area_start but ending before next_area_end
                case_i = next((j for j, (_, sz, _) in enumerate(pool)
                               if write_pos + sz > next_area_start
                               and write_pos + sz <= next_area_end), None)
                if case_i is not None:
                    idx, size, pixels = pool.pop(case_i)
                    _check_overflow(idx, size)
                    output[write_pos:write_pos + size] = pixels
                    new_ptrs[idx] = write_pos - pkg
                    corrector_pos[next_chunk_idx] = write_pos + size
                    corrector_set[next_chunk_idx] = True
                    write_pos += size + 2
                    continue

                # Case ii: smallest fitting entirely before next_area_start
                case_ii = next((j for j, (_, sz, _) in enumerate(pool)
                                if write_pos + sz <= next_area_start), None)
                if case_ii is not None:
                    idx, size, pixels = pool.pop(case_ii)
                    _check_overflow(idx, size)
                    output[write_pos:write_pos + size] = pixels
                    new_ptrs[idx] = write_pos - pkg
                    write_pos += size
                    continue

                # Case iii: all remaining sprites overflow next_area_end
                corrector_set[next_chunk_idx] = True
                write_pos = next_area_start + 2
                continue

            # No prospective area concern — write smallest sprite
            idx, size, pixels = pool[0]
            _check_overflow(idx, size)
            output[write_pos:write_pos + size] = pixels
            new_ptrs[idx] = write_pos - pkg
            write_pos += size
            pool.pop(0)

        elif write_pos >= area_start:
            # ── Rama B ──────────────────────────────────────────────────────────
            found = next((j for j, (_, sz, _) in enumerate(pool)
                          if write_pos + sz <= area_end), None)
            if found is not None:
                idx, size, pixels = pool.pop(found)
                output[write_pos:write_pos + size] = pixels
                new_ptrs[idx] = write_pos - pkg
                write_pos += size
            else:
                write_pos = area_end

        else:
            # ── Rama C ──────────────────────────────────────────────────────────
            if not corrector_set[chunk_idx]:
                # Case i: smallest sprite crossing area_start but ending before area_end
                case_i = next((j for j, (_, sz, _) in enumerate(pool)
                               if write_pos + sz > area_start
                               and write_pos + sz <= area_end), None)
                if case_i is not None:
                    idx, size, pixels = pool.pop(case_i)
                    _check_overflow(idx, size)
                    output[write_pos:write_pos + size] = pixels
                    new_ptrs[idx] = write_pos - pkg
                    corrector_pos[chunk_idx] = write_pos + size
                    corrector_set[chunk_idx] = True
                    write_pos += size + 2
                    continue

                # Case ii: smallest sprite that fits entirely before area_start
                case_ii = next((j for j, (_, sz, _) in enumerate(pool)
                                if write_pos + sz <= area_start), None)
                if case_ii is not None:
                    idx, size, pixels = pool.pop(case_ii)
                    _check_overflow(idx, size)
                    output[write_pos:write_pos + size] = pixels
                    new_ptrs[idx] = write_pos - pkg
                    write_pos += size
                    continue

                # Case iii: all remaining sprites overflow area_end
                # corrector stays at default (area_start, bytes 0-1)
                corrector_set[chunk_idx] = True
                write_pos = area_start + 2
                # next iteration: Rama B

            else:
                # Corrector already set but still before area_start — write smallest
                idx, size, pixels = pool[0]
                _check_overflow(idx, size)
                output[write_pos:write_pos + size] = pixels
                new_ptrs[idx] = write_pos - pkg
                write_pos += size
                pool.pop(0)

    end_ptr = write_pos - pkg

    data_start = pkg + PTR_TABLE_OFFSET + (n_sprites + 1) * 4
    used     = write_pos - data_start
    capacity = SPRITE_PKG_END - data_start
    logging.info(
        "Sprite placement: %d sprites placed, %d bytes used, %d bytes capacity, %d bytes margin",
        n_sprites, used, capacity, capacity - used,
    )

    return new_ptrs, corrector_pos, end_ptr

def write_sprite_package_header(output: bytearray, data_card: bytearray,
                                n_sprites: int, new_ptrs: list, end_ptr: int) -> None:
    """Write the sprite package header fields into output, copying fixed fields from data_card."""
    pkg = SPRITE_PACKAGE_START

    # Text identifier (+0x0000..+0x0017, 0x18 bytes) — copy from data_card
    output[pkg:pkg + 0x18] = data_card[pkg:pkg + 0x18]

    # Termination pointer (+0x0018)
    struct.pack_into("<I", output, pkg + 0x18, end_ptr ^ 0xFFFFFFFF)

    # Fixed fields (+0x0040..+0x0047, 2 × uint32) — copy from data_card
    output[pkg + 0x40:pkg + 0x48] = data_card[pkg + 0x40:pkg + 0x48]

    # n_sprites (+0x0048)
    struct.pack_into("<I", output, pkg + 0x48, n_sprites ^ 0xFFFFFFFF)

    # Pointer table: new_ptrs[0..n-1] followed by end_ptr as end marker
    for i, ptr in enumerate(new_ptrs):
        struct.pack_into("<I", output, pkg + PTR_TABLE_OFFSET + i * 4, ptr ^ 0xFFFFFFFF)
    struct.pack_into("<I", output, pkg + PTR_TABLE_OFFSET + n_sprites * 4, end_ptr ^ 0xFFFFFFFF)

def write_correctors(output: bytearray, targets: list, corrector_pos: list) -> None:
    """
    For each chunk, sum all logical uint16 words in the checksum area except the
    corrector position, then write the corrector value that makes the total equal target.
    """
    for c in range(NUM_CHUNKS):
        area = SPRITE_PACKAGE_START + c * CHUNK_SIZE + CHECKSUM_AREA_OFFSET
        cpos = corrector_pos[c]
        sum_rest = 0
        for i in range(0, CHECKSUM_AREA_SIZE, 2):
            addr = area + i
            if addr != cpos:
                sum_rest = (sum_rest + logical_u16(output, addr)) & 0xFFFF
        corrector = (targets[c] - sum_rest) & 0xFFFF
        struct.pack_into("<H", output, cpos, corrector ^ 0xFFFF)

def recalculate_checksum(data: bytearray) -> None:
    """Recompute the global checksum and write it to 0x3FFFFE."""
    total = 0
    for i in range(0, CHECKSUM_LOCATION, 2):
        if i not in GLOBAL_SKIP:
            total = (total + logical_u16(data, i)) & 0xFFFF
    struct.pack_into("<H", data, CHECKSUM_LOCATION, total ^ 0xFFFF)

def transfer(data_path: str, otp_path: str, output_path: str) -> None:
    data_card = read_bin(data_path)
    otp_card  = read_bin(otp_path)

    targets = chunk_checksums(otp_card)

    output = bytearray(data_card)
    output[0:HEADER_SIZE] = otp_card[0:HEADER_SIZE]   # header from OTP card

    n, ptrs, dims = read_sprite_metadata(data_card)
    sprites = extract_sprites(data_card, n, ptrs, dims)

    new_ptrs, corrector_pos, end_ptr = place_sprites(output, sprites, n)
    write_sprite_package_header(output, data_card, n, new_ptrs, end_ptr)
    write_correctors(output, targets, corrector_pos)

    recalculate_checksum(output)

    with open(output_path, "wb") as f:
        f.write(output)

def check_capacity(path: str) -> dict:
    """Dry-run sprite placement to check if all sprites fit without overflow."""
    data = read_bin(path)
    n, ptrs, dims = read_sprite_metadata(data)
    sprites = extract_sprites(data, n, ptrs, dims)
    scratch = bytearray(EXPECTED_SIZE)
    _, _, end_ptr = place_sprites(scratch, sprites, n)
    data_start = SPRITE_PACKAGE_START + PTR_TABLE_OFFSET + (n + 1) * 4
    used = SPRITE_PACKAGE_START + end_ptr - data_start
    capacity = SPRITE_PKG_END - data_start
    return {
        "name": card_name(data),
        "dim_id": dim_id(data),
        "n_sprites": n,
        "used": used,
        "capacity": capacity,
        "margin": capacity - used,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="bem_transfer",
        description="BEM Data Transfer — transfers content between Vital Bracelet BEM cards.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── transfer ──────────────────────────────────────────────────────────────
    p_tr = sub.add_parser("transfer",
        help="Transfer sprite data from one card into the OTP shell of another.")
    p_tr.add_argument("--data_card", required=True, metavar="FILE",
        help="Card whose sprite content will be transferred.")
    p_tr.add_argument("--target_card", required=True, metavar="FILE",
        help="Physical target card that provides the OTP signatures.")
    p_tr.add_argument("--output_card", metavar="FILE",
        help="Output file path (default: auto-generated next to data_card).")

    # ── info ──────────────────────────────────────────────────────────────────
    p_info = sub.add_parser("info",
        help="Show metadata for a BEM card file.")
    p_info.add_argument("--card", required=True, metavar="FILE",
        help="BEM card .bin file to inspect.")

    # ── check ─────────────────────────────────────────────────────────────────
    p_chk = sub.add_parser("check",
        help="Verify that sprite data fits in the sprite package (capacity dry-run).")
    p_chk.add_argument("cards", nargs="+", metavar="FILE",
        help="One or more BEM card .bin files to check.")

    args = parser.parse_args()

    if args.cmd == "transfer":
        out = args.output_card or make_output_name(args.data_card, args.target_card)
        try:
            transfer(args.data_card, args.target_card, out)
            print(f"OK  →  {out}")
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "info":
        try:
            data = read_bin(args.card)
            n, _, _ = read_sprite_metadata(data)
            print(f"File:     {args.card}")
            print(f"Name:     {card_name(data)}")
            print(f"dimId:    0x{dim_id(data):02X}")
            print(f"Sprites:  {n}")
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "check":
        col_file = max(len(c) for c in args.cards)
        col_file = max(col_file, 4)
        header = (f"{'FILE':<{col_file}}  {'NAME':<24}  {'dimId':<6}  "
                  f"{'SPRITES':>7}  {'USED':>9}  {'CAPACITY':>9}  {'MARGIN':>9}  STATUS")
        print(header)
        print("-" * len(header))
        any_error = False
        for path in args.cards:
            try:
                r = check_capacity(path)
                used_kb     = r["used"]     // 1024
                capacity_kb = r["capacity"] // 1024
                margin_kb   = r["margin"]   // 1024
                status = "OK" if r["margin"] >= 0 else "OVERFLOW"
                if r["margin"] < 0:
                    any_error = True
                fname = os.path.basename(path)
                print(f"{fname:<{col_file}}  {r['name']:<24}  0x{r['dim_id']:02X}    "
                      f"{r['n_sprites']:>7}  {used_kb:>7} KB  {capacity_kb:>7} KB  "
                      f"{margin_kb:>7} KB  {status}")
            except Exception as e:
                any_error = True
                fname = os.path.basename(path)
                print(f"{fname:<{col_file}}  {'':24}  {'':6}  {'':7}  {'':9}  {'':9}  {'':9}  ERROR: {e}")
        if any_error:
            sys.exit(1)


# ── GUI ────────────────────────────────────────────────────────────────────────

def make_output_name(data_path: str, otp_path: str) -> str:
    d = os.path.splitext(os.path.basename(data_path))[0]
    o = os.path.splitext(os.path.basename(otp_path))[0]
    folder = os.path.dirname(data_path)
    return os.path.join(folder, f"{d}__otp_{o}.bin")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BEM Data Transfer")
        self.resizable(False, False)
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        PAD = dict(padx=10, pady=6)

        # ── Data card ──────────────────────────────────────────────────────────
        frm_data = tk.LabelFrame(self, text=" Data card  (content to transfer) ", padx=8, pady=6)
        frm_data.grid(row=0, column=0, columnspan=2, sticky="ew", **PAD)

        self.data_path = tk.StringVar()
        self.data_name = tk.StringVar(value="—")
        self.data_dimid = tk.StringVar(value="—")

        tk.Entry(frm_data, textvariable=self.data_path, width=52, state="readonly").grid(row=0, column=0, padx=(0,4))
        tk.Button(frm_data, text="Browse…", command=self._pick_data).grid(row=0, column=1)
        tk.Label(frm_data, text="Name:").grid(row=1, column=0, sticky="w")
        tk.Label(frm_data, textvariable=self.data_name, anchor="w", width=54).grid(row=2, column=0, columnspan=2, sticky="w")
        tk.Label(frm_data, text="dimId:").grid(row=3, column=0, sticky="w")
        tk.Label(frm_data, textvariable=self.data_dimid, anchor="w").grid(row=4, column=0, sticky="w")

        # ── OTP card ───────────────────────────────────────────────────────────
        frm_otp = tk.LabelFrame(self, text=" OTP card  (signatures to use) ", padx=8, pady=6)
        frm_otp.grid(row=1, column=0, columnspan=2, sticky="ew", **PAD)

        self.otp_path = tk.StringVar()
        self.otp_name = tk.StringVar(value="—")
        self.otp_dimid = tk.StringVar(value="—")

        tk.Entry(frm_otp, textvariable=self.otp_path, width=52, state="readonly").grid(row=0, column=0, padx=(0,4))
        tk.Button(frm_otp, text="Browse…", command=self._pick_otp).grid(row=0, column=1)
        tk.Label(frm_otp, text="Name:").grid(row=1, column=0, sticky="w")
        tk.Label(frm_otp, textvariable=self.otp_name, anchor="w", width=54).grid(row=2, column=0, columnspan=2, sticky="w")
        tk.Label(frm_otp, text="dimId:").grid(row=3, column=0, sticky="w")
        tk.Label(frm_otp, textvariable=self.otp_dimid, anchor="w").grid(row=4, column=0, sticky="w")

        # ── Output ─────────────────────────────────────────────────────────────
        frm_out = tk.LabelFrame(self, text=" Output file ", padx=8, pady=6)
        frm_out.grid(row=2, column=0, columnspan=2, sticky="ew", **PAD)

        self.out_path = tk.StringVar()
        tk.Entry(frm_out, textvariable=self.out_path, width=52).grid(row=0, column=0, padx=(0,4))
        tk.Button(frm_out, text="Browse…", command=self._pick_output).grid(row=0, column=1)

        # ── Transfer button ────────────────────────────────────────────────────
        tk.Button(self, text="Transfer", width=20, command=self._run,
                  bg="#4a90d9", fg="white", font=("", 11, "bold")).grid(
            row=3, column=0, columnspan=2, pady=10)

        # ── Status bar ─────────────────────────────────────────────────────────
        self.status = tk.StringVar(value="Select both cards to begin.")
        tk.Label(self, textvariable=self.status, anchor="w", relief="sunken",
                 width=62).grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0,8))

    # ── File pickers ───────────────────────────────────────────────────────────

    def _pick_bin(self, path_var, name_var, dimid_var):
        path = filedialog.askopenfilename(
            title="Select BEM card .bin",
            filetypes=[("BEM card", "*.bin"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = read_bin(path)
            path_var.set(path)
            name_var.set(card_name(data))
            dimid_var.set(f"0x{dim_id(data):02X}")
            self._update_output_name()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _pick_data(self):
        self._pick_bin(self.data_path, self.data_name, self.data_dimid)

    def _pick_otp(self):
        self._pick_bin(self.otp_path, self.otp_name, self.otp_dimid)

    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="Save output as",
            defaultextension=".bin",
            filetypes=[("BEM card", "*.bin"), ("All files", "*.*")])
        if path:
            self.out_path.set(path)

    def _update_output_name(self):
        if self.data_path.get() and self.otp_path.get():
            self.out_path.set(make_output_name(self.data_path.get(), self.otp_path.get()))

    # ── Transfer ───────────────────────────────────────────────────────────────

    def _run(self):
        data = self.data_path.get()
        otp  = self.otp_path.get()
        out  = self.out_path.get()

        if not data or not otp:
            messagebox.showwarning("Missing files", "Please select both card files.")
            return
        if not out:
            messagebox.showwarning("Missing output", "Please specify an output file path.")
            return
        if data == otp:
            messagebox.showwarning("Same file", "Data card and OTP card cannot be the same file.")
            return

        self.status.set("Working…")
        self.update()

        try:
            transfer(data, otp, out)
            self.status.set(f"Done → {os.path.basename(out)}")
            messagebox.showinfo("Success", f"File written:\n{out}")
        except Exception as e:
            self.status.set(f"Error: {e}")
            messagebox.showerror("Transfer failed", str(e))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        _cli()
    else:
        App().mainloop()
