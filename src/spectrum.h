#pragma once
#include <stdint.h>

constexpr int kSpectrumBins = 512;
constexpr int kBurstFilterFrames = 7;
// Exponential power averaging weight per frame (lower = smoother, slower).
constexpr float kPowerAverageAlpha = 0.15f;
constexpr int kCaptureCenterMHz = 2406;  // default; runtime value: gCaptureCenterMHz
extern volatile int gCaptureCenterMHz;
constexpr int kCaptureSpanKHz = 16000;
constexpr uint8_t kCaptureClock = 0;  // ESP32 hardware clock: 16 MS/s.
inline int captureLowKHz() { return gCaptureCenterMHz * 1000 - kCaptureSpanKHz / 2; }
// QO-100 WB bandplan V3: 10490.5..10499.5 MHz downlink, minus 8089.5 MHz.
constexpr int kBandLowKHz = 2401000;
constexpr int kBandHighKHz = 2410000;
// The displayed band follows the capture centre (default centre 2406 -> 2401..2410 MHz).
inline int bandLowKHz() { return kBandLowKHz + (gCaptureCenterMHz - kCaptureCenterMHz) * 1000; }
inline int bandHighKHz() { return kBandHighKHz + (gCaptureCenterMHz - kCaptureCenterMHz) * 1000; }
static_assert(kBandLowKHz >= kCaptureCenterMHz * 1000 - kCaptureSpanKHz / 2 &&
              kBandHighKHz < kCaptureCenterMHz * 1000 + kCaptureSpanKHz / 2,
              "Capture must contain the entire DATV band");

// View modes: narrow = one 16 MHz capture around gCaptureCenterMHz (31.25 kHz bins);
// wlan/max = stepped sweep of 12 MHz windows stitched into 512 display bins.
enum RangeMode { kRangeNarrow = 0, kRangeWlan = 1, kRangeMax = 2, kRangeCustom = 3 };
extern volatile int gRangeMode;
extern volatile int gRangeLowMHz, gRangeHighMHz;   // used by kRangeCustom ("range <lo> <hi>")
constexpr int kWlanLowMHz = 2400, kWlanHighMHz = 2484;
constexpr int kMaxLowMHz = 2300, kMaxHighMHz = 2500;
constexpr int kSweepStepKHz = 12000;     // usable part of each 16 MHz capture
constexpr int kSweepWindowBins = 384;    // 12 MHz / 31.25 kHz
constexpr int kSweepMaxWindows = 17;

struct SpectrumFrame {
    bool wide = false;
    int16_t lowMHz = 0, highMHz = 0;
    uint8_t bins[kSpectrumBins] = {};
    bool valid = false;
    bool burstFiltered = false;
    uint16_t clipped = 0;
    uint8_t gain = 40;
    char error[48] = {};
};

// Shared mapping keeps the plot and waterfall on exactly the same RF axis.
int spectrumBinForPixel(int pixel, int width);

class SpectrumProcessor {
public:
    SpectrumProcessor();
    void reset();
    void setBurstFilterEnabled(bool enabled);
    void setRawMode(bool raw);   // no averaging, no burst filter (used while sweeping)
    void process(const uint32_t* samples, SpectrumFrame& frame);

private:
    void fft();
    float re_[kSpectrumBins] = {};
    float im_[kSpectrumBins] = {};
    float power_[kSpectrumBins] = {};
    // Median instantaneous power BEFORE averaging, so bursts leave no EMA tail.
    float history_[kBurstFilterFrames][kSpectrumBins] = {};
    float window_[kSpectrumBins] = {};
    float twRe_[kSpectrumBins / 2] = {};
    float twIm_[kSpectrumBins / 2] = {};
    bool primed_ = false;
    bool raw_ = false;
    bool burstFilterEnabled_ = true;
    int historyHead_ = 0;
    int historyCount_ = 0;
};
