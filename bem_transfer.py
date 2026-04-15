"""
BEM Data Transfer
Transfers the content of one Vital Bracelet BEM card into the OTP shell of another,
allowing cards to be used on physical cards with a different OTP.
"""

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

def adjust_correctors(output: bytearray, targets: list[int]) -> None:
    """Overwrite the 2-byte corrector of each chunk area so its sum equals the target."""
    for n in range(NUM_CHUNKS):
        area = SPRITE_PACKAGE_START + n * CHUNK_SIZE + CHECKSUM_AREA_OFFSET
        # Sum the area without the corrector (bytes 2 onwards)
        sum_rest = 0
        for i in range(2, CHECKSUM_AREA_SIZE, 2):
            sum_rest = (sum_rest + logical_u16(output, area + i)) & 0xFFFF
        new_logical = (targets[n] - sum_rest) & 0xFFFF
        struct.pack_into("<H", output, area, new_logical ^ 0xFFFF)  # re-NOT for disk

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

    adjust_correctors(output, targets)
    recalculate_checksum(output)

    with open(output_path, "wb") as f:
        f.write(output)

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
    App().mainloop()
