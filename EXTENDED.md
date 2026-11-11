# Extended version by DG7NDV

This fork of [HB9IIU/ESP32-CYD-pocket-qo-100-spectrum-viewer](https://github.com/HB9IIU/ESP32-CYD-pocket-qo-100-spectrum-viewer)
keeps everything of the original (touch gestures, trace styles, waterfall palettes, CF/SR estimator)
and adds a **tunable receive frequency (2300–2500 MHz)**, two **wide sweep views**, a **touch menu**, **tap markers (up to 4, with band power)**, **max hold**, **touch zoom** and a few **serial commands**.

Version 1.5 (firmware binaries: see the GitHub Releases page). Original work: HB9IIU. Extensions: DG7NDV (2026). Licence stays Apache-2.0, see `docs/LICENSE` and `docs/NOTICE`.

> **Status:** developed and tested only on the 2.8" CYD (type ESP32-2432S028, `CYD28Inch`) with an
> [ESP32-DATV](https://github.com/SP8ESA/ESP32-DATV) transmitter as signal source. The 4" build compiles
> from the same sources but was not tried. Items marked *untested* below were built but not verified on hardware.

---

## 1. Frequency range and how to switch it

The ESP32 Wi-Fi radio is used as a 16 MS/s I/Q receiver. One capture shows a **16 MHz window** with
31.25 kHz bins. The original firmware was fixed to 2406 MHz (2401–2410 MHz QO-100 DATV uplink).
This fork lets you move that window and also sweep wider ranges:

| View | Range | How it is built | Resolution |
|---|---|---|---|
| **QO-100** (default, `qo100`) | 2401–2410 MHz, window centred on 2406 MHz | one capture | 31.25 kHz/bin, CF and SR estimate |
| **Centre** (`freq <MHz>`) | any 16 MHz window, centre **2300–2500 MHz** | one capture | 31.25 kHz/bin, CF and SR estimate |
| **WLAN** (`rangewlan`) | 2400–2484 MHz | 7 stepped windows of 12 MHz | ~164 kHz/bin (peak hold) |
| **Max** (`maxrange`) | 2300–2500 MHz | 17 stepped windows of 12 MHz | ~390 kHz/bin (peak hold) |

In the two sweep views the display shows `SWEEP 2300-2500 MHz | 390 kHz/bin`, the range edges in the strip
above the waterfall, and the strongest bin is printed on USB serial every 2 s as `[pk] 2403.8 MHz level=180`.
CF/SR estimation is only done in the single-window views.

### Switching

**USB serial** (115200 baud, e.g. `pio device monitor`):

```text
freq 2370        centre the 16 MHz window on 2370 MHz (integer MHz, 2300..2500)
qo100            back to the default QO-100 view (centre 2406 MHz)
rangewlan        sweep 2400-2484 MHz
maxrange         sweep 2300-2500 MHz
range 2380 2430  sweep any range: start < end, 2300..2500 MHz, at most 204 MHz wide
stop / start     pause / resume the receiver
status           print centre frequency and the current CF/SR result
```

**Config menu:** tap the **`C` button in the top-right corner**. The menu opens at once with `QO-100`, `WLAN`,
`MAX` (a tap applies the view immediately and returns to the spectrum), centre buttons `-10 -1 +1 +10`, `HOLD`
and `OK` (applies a changed centre). The red `C` in the top-right corner of the menu closes it without changing anything.
There is no Wi-Fi or web page any more (removed in 1.3).

**Main screen (1.4):**

| Action | Effect |
|---|---|
| Tap in the spectrum | marker (up to 4: M1 yellow, M2 magenta, M3 green, M4 orange); a table at the top left shows for each marker the tapped frequency, the strongest bin nearby and its level. With two markers it also shows the frequency/level difference and the **band power between M1 and M2** (sum of the bin powers, relative dBFS). Tap next to a marker to clear it; with all four set the next tap replaces the oldest. Serial: `marker`, `marker clear`. Markers are cleared when the view changes. |
| Press, hold and drag sideways | zoom into that frequency range: up to 12 MHz = zoomed single capture (31.25 kHz/bin), wider = sweep of that range |
| Double tap or the **`N`** button (top left, next to `HOLD`) | back to the view before the first zoom (without zoom the double tap toggles the layout as in the original) |
| **`HOLD`** button (top left) | max hold: a yellow line keeps the highest value per bin; tap again to switch off and clear |
| Tap in the waterfall | cycle the waterfall palette (as in the original) |

In the sweep views the strongest bin that stands about 10 dB above the noise is shown as `PK 2403.8 MHz` in the strip
above the waterfall. The title says "QO-100 Uplink Spectrum Viewer" only in the QO-100 view (centre 2406 MHz),
otherwise "Spectrum Viewer". The trace style is changed with the serial command `mode`.

Notes and limits:

- The 2300–2500 MHz limit is a software check (`esp_sdr.cpp`, `kFreq*` in `main.cpp`); windows are allowed
  from 2290 to 2510 MHz. The lower end matches the 2300–2450 MHz range that ESP32-DATV permits for transmit.
  Whether the receiver front end stays sensitive far from the Wi-Fi band was only spot-checked (see below).
- The frequency is programmed through the ESP32 ROM (`rom_set_rf_freq_offset`) in whole MHz. The firmware only
  reports "tune requested"; it cannot verify PLL lock itself, you need a signal source to verify.
- Measured with an [ESP32-DATV](https://github.com/SP8ESA/ESP32-DATV) transmitter (DVB-S2, QPSK, 500 kBd,
  FEC 3/5, test pattern, 22 s per frequency; the viewer centre was set to the nearest MHz with `freq`).
  The CF reported by the viewer is **about +90 … +110 kHz high**, nearly constant over the whole range:

  | Transmitter (MHz) | Viewer CF (MHz) | Error |
  |---|---|---|
  | 2310.000 | 2310.088 | +88 kHz |
  | 2350.000 | 2350.088 | +88 kHz |
  | 2380.000 | 2380.099 | +99 kHz |
  | 2403.750 | 2403.857 | +107 kHz |
  | 2420.000 | 2420.101 | +101 kHz |
  | 2445.000 | 2445.091 | +91 kHz |

  The symbol rate was recognised as 500 ksps at every frequency. A constant offset (not proportional to the
  frequency) points to a fixed offset of the viewer's bin-to-frequency mapping rather than to a crystal error in ppm,
  but part of it may also come from the transmitter's own crystal. The viewer's resolution is 31.25 kHz per bin.

  **Correction:** `cal <kHz>` adds a fixed correction to the displayed CF (saved in flash), e.g. `cal -95`;
  `calref 2403.750` sets it automatically while a transmitter of that known frequency is detected. `cal` shows the
  current value. Storing and reading `cal` was checked on the board; the effect on the CF readout was not verified
  after the measurements above. Note that a correction tuned on one transmitter also hides that transmitter's own
  frequency error, so check against a known-good reference when you can.

## 2. Serial commands (all)

| Command | Meaning |
|---|---|
| `freq <MHz>` | centre of the single-window view, 2300..2500 |
| `qo100` / `rangewlan` / `maxrange` | view modes (table above) |
| `range <start> <end>` | sweep a free range in whole MHz (2300..2500, max. 204 MHz wide; invalid values are rejected) |
| `stop` / `start` | pause / resume |
| `hold [on\|off\|clear]` | max hold line (`hold` toggles) |
| `marker [clear]` | print / clear the tap markers (`[mk]`, `[band]` lines) |
| `status` | centre frequency + CF/SR |
| `cal <kHz>` | add a fixed kHz correction to the displayed CF (saved in flash) |
| `calref <MHz>` | with a signal present: set the correction so CF shows this reference, e.g. `calref 2403.750` |
| `cal` | show the current correction |
| `layout`, `mode`, `wf`, `burst`, `help` | unchanged from the original |

Debug lines: `[ui] …` (menu open/closed, taps, drags), `[zoom] …`, `[mk] …`, `[band] …` and `[hold] …`; with the touch coordinates `[touch] raw=…` they show what a tap did.

In sweep views the peak is printed as `[pk] 2403.8 MHz level=215`, or `[pk] none` when nothing stands clearly above the noise. The outermost bins are ignored. In the 2300–2500 MHz sweep strong peaks were seen at 2400.1 and 2440.0 MHz without a deliberate source; it was not clarified whether they are real signals or receiver artefacts.

Machine-readable output on USB: `[cf] 2403.859 MHz sr=500 ksps` (or `[cf] none`) in the single-window views,
whenever the value changes and every 2 s while a signal is detected.

The per-second `[touch] idle …` debug lines of the original are muted.

## 3. Menu

See section 1 (touch menu). The receiver keeps running behind the menu. Wi-Fi, access point, web page and
web firmware update were part of 1.2 and are removed in 1.3.

## 4. Other changes

- The header shows `by HB9IIU, extended by DG7NDV`, also on the splash screen.
- The spectrum processor is allocated on the heap (static DRAM was full after adding the new features).
- The earlier attempt to reboot into the ROM download mode from software did not work on the tested board and was removed; flash with the BOOT button.

## 5. Control GUI (`tools/spek_control.py`)

Small Python/tkinter program for the USB serial port (needs `pip install pyserial`; tkinter ships with Python,
Linux: `sudo apt install python3-tk`). Tested on Linux only, Windows/macOS should work but are untested.

```bash
python3 tools/spek_control.py
```

Port selection with auto-search, Start / Stop / Status, QO-100 / WLAN / MAX buttons, start and end frequency
boxes (type or mouse wheel per digit, saved), a `Hold` button, 10 memory slots (click = recall or store, right click = overwrite,
L = delete, R = rename) and a large display of the received CF / symbol rate / peak. Opening the port resets the
board on many systems, so wait ~7 s after connecting.

## 6. Build and flash

```bash
pio run -e CYD28Inch -j 2
pio run -e CYD28Inch -t upload --upload-port /dev/ttyUSB0     # BOOT held while plugging in, if needed
```

With a system `pio` that is too old/new for your Python, a virtualenv with `pip install platformio` works.
The browser installer linked at the top of the original README installs the **original** firmware.

## 7. Files changed

`src/main.cpp` (menu, serial commands, sweep, CF output), `src/spectrum.{h,cpp}` (runtime centre, raw mode),
`src/esp_sdr.{h,cpp}` (wider tuning range, `espSdrEnd`, quiet retune), `src/touch_input.cpp` (idle log muted),
`tools/spek_control.py`, this file.
