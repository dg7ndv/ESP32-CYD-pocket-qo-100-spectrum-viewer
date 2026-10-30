#!/usr/bin/env python3
"""Steuerung DG7NDV - ESP32 Mini Spek.

Kleine Bedienoberflaeche fuer den erweiterten ESP32-CYD QO-100 Spektrum-Viewer ueber die
serielle USB-Schnittstelle (115200 Baud). Laeuft unter Linux, Windows und macOS.

  pip install pyserial        (tkinter ist bei Python meist dabei; Linux: sudo apt install python3-tk)
  python spek_control.py

Start / Stop      Empfaenger anhalten / fortsetzen
QO-100 / WLAN / MAX Ansicht umschalten (siehe EXTENDED.md)
Start / Ende      Frequenzbereich [MHz] fuer den Durchlauf ("range <start> <ende>", Firmware ab "range"-Version):
                  eintippen oder mit dem Mausrad ueber einer Ziffer stellenweise aendern; wird gespeichert
10 Speicher       leerer Speicher: Klick speichert die aktuelle Einstellung
                  belegter Speicher: Klick ruft sie auf, Rechtsklick ueberschreibt sie
                  L = loeschen, R = umbenennen (kleine Knoepfe daneben)
Die Speicher stehen in ~/.dg7ndv_spek_control.json.
Hinweis: Beim Verbinden startet das Board je nach Treiber/System neu (Startbild ca. 6 s).
"""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    raise SystemExit("pyserial fehlt: pip install pyserial")

TITLE = "Steuerung DG7NDV  ESP32 Mini Spek"
BAUD = 115200
SLOTS = 10
CONFIG = Path.home() / ".dg7ndv_spek_control.json"
FREQ_MIN, FREQ_MAX = 2300, 2500
RANGE_MIN, RANGE_MAX = 2290, 2510      # Grenzen der Firmware fuer "range"
RANGE_MAX_SPAN = 204                   # 17 Fenster zu 12 MHz
NUM_FONT = ("TkDefaultFont", 22, "bold")
BIG_FONT = ("TkDefaultFont", 22, "bold")
COL_CF, COL_SR, COL_PK, COL_OFF = "#0a7a2f", "#b36b00", "#9a6b00", "#9aa0a6"
COL_ENTRY = "#0a5fb4"
MODES = {"qo100": "QO-100", "rangewlan": "WLAN", "maxrange": "MAX"}


class Link:
    """Serielle Verbindung zum Viewer, liest Zeilen in einem Thread."""

    def __init__(self, on_line):
        self.on_line = on_line
        self.port = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def connected(self):
        return self.port is not None and self.port.is_open

    def open(self, name):
        port = serial.Serial()
        port.port = name
        port.baudrate = BAUD
        port.timeout = 0.2
        port.dtr = False   # kein Reset des Boards beim Oeffnen (CH340: RTS haengt an EN)
        port.rts = False
        port.open()
        self.port = port
        self._stop.clear()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self.port:
            try:
                self.port.close()
            finally:
                self.port = None

    def send(self, text):
        if not self.connected:
            raise RuntimeError("erst oben auf Verbinden klicken")
        self.port.write((text.strip() + "\n").encode())

    def _read(self):
        buf = b""
        while not self._stop.is_set():
            try:
                data = self.port.read(256)
            except (serial.SerialException, OSError, TypeError):
                self.on_line("[verbindung verloren]")
                return
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                if text:
                    self.on_line(text)


def probe(device, seconds=9.0):
    """True, wenn auf 'status' ein Spek antwortet. Nur fuer CH340-Ports; das Board kann dabei neu starten."""
    port = serial.Serial()
    port.port, port.baudrate, port.timeout = device, BAUD, 0.2
    port.dtr = port.rts = False
    try:
        port.open()
    except (serial.SerialException, OSError):
        return False
    try:
        import time
        end = time.time() + seconds
        next_ask = 0.0
        buf = b""
        while time.time() < end:
            if time.time() >= next_ask:
                port.write(b"status\n")
                next_ask = time.time() + 1.5
            buf += port.read(256)
            if b"[rx]" in buf and (b"centre frequency" in buf or b"QO-100 DATV" in buf):
                return True
        return False
    except (serial.SerialException, OSError):
        return False
    finally:
        port.close()


class Memory:
    """10 Speicherplaetze: {"name": str, "cmd": "freq 2370" | "qo100" | ...} oder None."""

    def __init__(self, path=CONFIG):
        self.path = path
        self.slots = [None] * SLOTS
        self.settings = {"start": 2300, "end": 2500}
        self.load()

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key in ("start", "end"):
                value = data.get("settings", {}).get(key)
                if isinstance(value, int) and RANGE_MIN <= value <= RANGE_MAX:
                    self.settings[key] = value
            for i, slot in enumerate(data.get("slots", [])[:SLOTS]):
                if isinstance(slot, dict) and "cmd" in slot:
                    self.slots[i] = {"name": str(slot.get("name", "")), "cmd": str(slot["cmd"])}
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            self.path.write_text(json.dumps({"settings": self.settings, "slots": self.slots}, indent=1), encoding="utf-8")
        except OSError as err:
            messagebox.showerror("Speichern", f"{self.path}: {err}")


def describe(cmd):
    if cmd.startswith("freq "):
        return cmd[5:] + " MHz"
    if cmd.startswith("range "):
        return cmd[6:].replace(" ", "-") + " MHz"
    return MODES.get(cmd, cmd)


class DigitEntry(ttk.Entry):
    """Ganzzahl-Feld: tippen oder Mausrad ueber einer Ziffer = diese Stelle um 1 aendern."""

    def __init__(self, master, value, on_change, **kw):
        self.var = tk.StringVar(value=str(value))
        kw.setdefault("font", NUM_FONT)
        kw.setdefault("foreground", COL_ENTRY)
        super().__init__(master, textvariable=self.var, justify="right", **kw)
        self.on_change = on_change
        self.bind("<MouseWheel>", self._wheel)                              # Windows / macOS
        self.bind("<Button-4>", lambda e: self._step(e, +1))                # Linux
        self.bind("<Button-5>", lambda e: self._step(e, -1))
        self.bind("<Return>", lambda _e: self.on_change())
        self.bind("<FocusOut>", lambda _e: self.on_change())

    def get_int(self):
        try:
            return int(self.var.get().strip())
        except ValueError:
            return None

    def set_int(self, value):
        self.var.set(str(int(value)))

    def _wheel(self, event):
        self._step(event, +1 if event.delta > 0 else -1)

    def _step(self, event, direction):
        value = self.get_int()
        text = self.var.get().strip()
        if value is None or not text:
            return "break"
        pos = min(max(self.index(f"@{event.x}"), 0), len(self.var.get()) - 1)
        offset = len(self.var.get()) - len(text.lstrip())   # fuehrende Leerzeichen
        place = len(text) - 1 - max(pos - offset, 0)
        value = min(max(value + direction * 10 ** max(place, 0), RANGE_MIN), RANGE_MAX)
        self.set_int(value)
        self.on_change()
        return "break"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.resizable(False, False)
        self.lines = queue.Queue()
        self.link = Link(self.lines.put)
        self.memory = Memory()
        self.current_cmd = "qo100"    # zuletzt gesendete Ansicht, wird beim Speichern abgelegt
        self._build()
        self._refresh_ports()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ------------------------------------------------------------------ aufbau
    def _build(self):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(self, text=TITLE, font=("TkDefaultFont", 15, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4))

        top = ttk.Frame(self)
        top.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
        self.port_var = tk.StringVar()
        self.ports = {}
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=34, state="readonly")
        self.port_box.pack(side="left")
        ttk.Button(top, text="Neu lesen", width=9, command=self._refresh_ports).pack(side="left", padx=4)
        self.search_btn = ttk.Button(top, text="Suchen", width=8, command=self._search)
        self.search_btn.pack(side="left", padx=(0, 4))
        self.connect_btn = ttk.Button(top, text="Verbinden", width=11, command=self._toggle_connect)
        self.connect_btn.pack(side="left")

        run = ttk.Frame(self)
        run.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(run, text="Start", width=10, command=lambda: self._send("start")).pack(side="left")
        ttk.Button(run, text="Stop", width=10, command=lambda: self._send("stop")).pack(side="left", padx=4)
        ttk.Button(run, text="Status", width=8, command=lambda: self._send("status")).pack(side="left")

        centre = ttk.Frame(self)
        centre.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        for cmd, label in MODES.items():
            ttk.Button(centre, text=label, width=7, command=lambda c=cmd: self._send(c, remember=True)).pack(
                side="left", padx=2)

        span = ttk.Frame(self)
        span.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(span, text="Start").pack(side="left")
        self.start_box = DigitEntry(span, self.memory.settings["start"], self._range_edited, width=5)
        self.start_box.pack(side="left", padx=4)
        ttk.Label(span, text="Ende").pack(side="left")
        self.end_box = DigitEntry(span, self.memory.settings["end"], self._range_edited, width=5)
        self.end_box.pack(side="left", padx=4)
        ttk.Label(span, text="MHz").pack(side="left")
        ttk.Button(span, text="Bereich", width=8, command=self._set_range).pack(side="left", padx=6)
        ttk.Label(span, text="(Mausrad ueber einer Ziffer)").pack(side="left")

        self.info_var = tk.StringVar(value="Nicht verbunden")
        ttk.Label(self, textvariable=self.info_var).grid(row=5, column=0, columnspan=2, sticky="w", padx=8)
        big = ttk.Frame(self)
        big.grid(row=6, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 4))
        self.cf_var = tk.StringVar(value="--- MHz")
        self.sr_var = tk.StringVar(value="")
        self.cf_label = ttk.Label(big, textvariable=self.cf_var, font=BIG_FONT, foreground=COL_OFF)
        self.cf_label.pack(side="left")
        self.sr_label = ttk.Label(big, textvariable=self.sr_var, font=("TkDefaultFont", 16, "bold"), foreground=COL_SR)
        self.sr_label.pack(side="right")

        mem = ttk.LabelFrame(self, text="Speicher (leer: Klick speichert, Rechtsklick ueberschreibt)")
        mem.grid(row=7, column=0, columnspan=2, sticky="ew", padx=6, pady=4)
        self.slot_buttons = []
        for i in range(SLOTS):
            col, row = divmod(i, 5)
            cell = ttk.Frame(mem)
            cell.grid(row=row, column=col, padx=6, pady=2, sticky="w")
            btn = ttk.Button(cell, width=24, command=lambda n=i: self._slot_click(n))
            btn.pack(side="left")
            btn.bind("<Button-3>", lambda _e, n=i: self._slot_store(n))
            small = {"width": 2}
            ttk.Button(cell, text="L", command=lambda n=i: self._slot_clear(n), **small).pack(side="left", padx=(3, 0))
            ttk.Button(cell, text="R", command=lambda n=i: self._slot_rename(n), **small).pack(side="left")
            self.slot_buttons.append(btn)
        self._refresh_slots()

        self.log = tk.Text(self, height=7, width=78, state="disabled", font=("TkFixedFont", 9))
        self.log.grid(row=8, column=0, columnspan=2, padx=6, pady=(2, 8))

    # ------------------------------------------------------------------ seriell
    def _refresh_ports(self):
        # Nur echte USB-Seriellgeraete (keine leeren ttyS*); der CYD (CH340 1a86:7523) wird bevorzugt.
        found = [p for p in list_ports.comports() if p.vid is not None]
        found.sort(key=lambda p: (p.vid, p.pid) != (0x1A86, 0x7523))
        self.ports = {f"{p.device} - {p.description}": p.device for p in found}
        self.port_box["values"] = list(self.ports)
        if self.ports and self.port_var.get() not in self.ports:
            self.port_var.set(next(iter(self.ports)))

    def _search(self):
        """Fragt alle CH340-Ports mit 'status' ab und verbindet mit dem ersten, der wie der Spek antwortet."""
        if self.link.connected:
            self._toggle_connect()
        candidates = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x1A86, 0x7523)]
        if not candidates:
            messagebox.showinfo("Suchen", "Kein CH340-Port gefunden (CYD angesteckt?).")
            return
        self.search_btn.config(state="disabled")
        self.info_var.set("Suche Spek an: " + ", ".join(candidates) + " ...")

        def worker():
            hit = next((d for d in candidates if probe(d)), None)
            self.after(0, lambda: self._search_done(hit))

        threading.Thread(target=worker, daemon=True).start()

    def _search_done(self, device):
        self.search_btn.config(state="normal")
        if not device:
            self.info_var.set("Kein Spek gefunden")
            return
        for label, dev in self.ports.items():
            if dev == device:
                self.port_var.set(label)
        self._toggle_connect()

    def _toggle_connect(self):
        if self.link.connected:
            self.link.close()
            self.connect_btn.config(text="Verbinden")
            self.info_var.set("Nicht verbunden")
            return
        name = self.ports.get(self.port_var.get())
        if not name:
            messagebox.showinfo("Port", "Kein serieller Port gefunden.")
            return
        try:
            self.link.open(name)
        except (serial.SerialException, OSError) as err:
            messagebox.showerror("Verbinden", f"{name}: {err}")
            return
        self.connect_btn.config(text="Trennen")
        # Das Oeffnen des Ports kann das Board neu starten (Startbild ca. 6 s): erst danach abfragen.
        self.info_var.set(f"Verbunden mit {name} - Board startet ...")
        self.after(7000, lambda: self.link.connected and self._send("status"))

    def _send(self, cmd, remember=False):
        try:
            self.link.send(cmd)
        except (RuntimeError, serial.SerialException, OSError) as err:
            self._log(f"Senden fehlgeschlagen: {err}")
            return False
        self._log(f"> {cmd}")
        if remember:
            self.current_cmd = cmd
        return True

    def _range_values(self, message=True):
        start, end = self.start_box.get_int(), self.end_box.get_int()
        problem = None
        if start is None or end is None:
            problem = "Start und Ende als ganze MHz eingeben."
        elif not (RANGE_MIN <= start < end <= RANGE_MAX):
            problem = f"Erlaubt: {RANGE_MIN} <= Start < Ende <= {RANGE_MAX} MHz."
        elif end - start > RANGE_MAX_SPAN:
            problem = f"Der Bereich darf hoechstens {RANGE_MAX_SPAN} MHz breit sein."
        if problem:
            if message:
                messagebox.showinfo("Bereich", problem)
            return None
        return start, end

    def _range_edited(self):
        """Gueltige Werte sofort in der Konfiguration merken (auch beim Drehen am Mausrad)."""
        values = self._range_values(message=False)
        if values:
            self.memory.settings["start"], self.memory.settings["end"] = values
            self.memory.save()

    def _set_range(self):
        values = self._range_values()
        if values:
            self._range_edited()
            self._send("range %d %d" % values, remember=True)

    # ------------------------------------------------------------------ speicher
    def _slot_label(self, i):
        slot = self.memory.slots[i]
        if not slot:
            return f"{i + 1}: (leer)"
        name = slot["name"] or "-"
        return f"{i + 1}: {name}  {describe(slot['cmd'])}"

    def _refresh_slots(self):
        for i, btn in enumerate(self.slot_buttons):
            btn.config(text=self._slot_label(i))

    def _current_setting(self):
        """Was gerade eingestellt ist: Ansicht oder Bereich (None, wenn noch nichts gewaehlt)."""
        if self.current_cmd in MODES or self.current_cmd.startswith("range "):
            return self.current_cmd
        return None

    def _slot_store(self, i):
        cmd = self._current_setting()
        if not cmd:
            messagebox.showinfo("Speicher", "Erst einen Bereich setzen oder eine Ansicht waehlen.")
            return
        old = self.memory.slots[i]
        name = old["name"] if old else f"M{i + 1}"
        self.memory.slots[i] = {"name": name, "cmd": cmd}
        self.memory.save()
        self._refresh_slots()

    def _slot_click(self, i):
        slot = self.memory.slots[i]
        if not slot:
            self._slot_store(i)
            return
        cmd = slot["cmd"]
        if self._send(cmd, remember=True):
            if cmd.startswith("range "):
                start, end = cmd[6:].split()
                self.start_box.set_int(start)
                self.end_box.set_int(end)
                self._range_edited()

    def _slot_clear(self, i):
        if self.memory.slots[i] and messagebox.askyesno("Loeschen", f"Speicher {i + 1} loeschen?"):
            self.memory.slots[i] = None
            self.memory.save()
            self._refresh_slots()

    def _slot_rename(self, i):
        slot = self.memory.slots[i]
        if not slot:
            return
        name = simpledialog.askstring("Umbenennen", f"Name fuer Speicher {i + 1}:", initialvalue=slot["name"], parent=self)
        if name is not None:
            slot["name"] = name.strip()[:14]
            self.memory.save()
            self._refresh_slots()

    # ------------------------------------------------------------------ anzeige
    def _log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 200:
            self.log.delete("1.0", f"{lines - 200}.0")
        self.log.see("end")
        self.log.config(state="disabled")

    def _show_cf(self, text):
        """'2403.859 MHz sr=500 ksps' oder 'none'."""
        parts = text.split()
        if len(parts) >= 3 and parts[1] == "MHz":
            self.cf_var.set(f"{parts[0]} MHz")
            self.sr_var.set(parts[2].replace("sr=", "SR ") + (" ksps" if len(parts) > 3 else ""))
            self.cf_label.config(foreground=COL_CF)
        else:
            self.cf_var.set("--- MHz")
            self.sr_var.set("")
            self.cf_label.config(foreground=COL_OFF)

    def _show_peak(self, text):
        """'2403.8 MHz level=180' aus dem Durchlauf."""
        parts = text.split()
        if len(parts) >= 2 and parts[1] == "MHz":
            self.cf_var.set(f"{parts[0]} MHz")
            self.sr_var.set("Spitze")
            self.cf_label.config(foreground=COL_PK)

    def _poll(self):
        try:
            while True:
                line = self.lines.get_nowait()
                if line.startswith("[cf]"):
                    self._show_cf(line[4:].strip())
                elif line.startswith("[pk]"):
                    self._show_peak(line[4:].strip())
                if not line.startswith(("[touch]", "[sdr]")):
                    self._log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _quit(self):
        self.link.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
