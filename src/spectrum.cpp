#include "spectrum.h"
#include <math.h>

namespace {
constexpr float kPi = 3.14159265358979323846f;
int signed10(uint32_t value) {
    const int field = value & 1023;
    return field >= 512 ? field - 1024 : field;
}
}

volatile int gCaptureCenterMHz = kCaptureCenterMHz;
volatile int gRangeMode = kRangeNarrow;
volatile int gRangeLowMHz = kMaxLowMHz, gRangeHighMHz = kMaxHighMHz;

int spectrumBinForPixel(int pixel, int width) {
    if (width < 2) return 0;
    if (gRangeMode != kRangeNarrow)   // wide frames already span the whole view
        return (pixel * (kSpectrumBins - 1) + (width - 1) / 2) / (width - 1);
    const int frequency = bandLowKHz()
        + pixel * (bandHighKHz() - bandLowKHz()) / (width - 1);
    int bin = ((frequency - captureLowKHz()) * kSpectrumBins
               + kCaptureSpanKHz / 2) / kCaptureSpanKHz;
    if (bin < 0) bin = 0;
    if (bin >= kSpectrumBins) bin = kSpectrumBins - 1;
    return bin;
}

SpectrumProcessor::SpectrumProcessor() {
    for (int i = 0; i < kSpectrumBins; ++i)
        window_[i] = 0.5f * (1.0f - cosf(2.0f * kPi * i / (kSpectrumBins - 1)));
    for (int i = 0; i < kSpectrumBins / 2; ++i) {
        const float angle = -2.0f * kPi * i / kSpectrumBins;
        twRe_[i] = cosf(angle);
        twIm_[i] = sinf(angle);
    }
}

void SpectrumProcessor::reset() {
    primed_ = false;
    historyHead_ = 0;
    historyCount_ = 0;
}

void SpectrumProcessor::setRawMode(bool raw) {
    if (raw == raw_) return;
    raw_ = raw;
    reset();
}

void SpectrumProcessor::setBurstFilterEnabled(bool enabled) {
    if (enabled == burstFilterEnabled_) return;
    burstFilterEnabled_ = enabled;
    reset();
}

void SpectrumProcessor::fft() {
    for (int i = 1, j = 0; i < kSpectrumBins; ++i) {
        int bit = kSpectrumBins >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) {
            float value = re_[i]; re_[i] = re_[j]; re_[j] = value;
            value = im_[i]; im_[i] = im_[j]; im_[j] = value;
        }
    }
    for (int length = 2; length <= kSpectrumBins; length <<= 1) {
        const int half = length / 2, stride = kSpectrumBins / length;
        for (int i = 0; i < kSpectrumBins; i += length) {
            for (int j = 0; j < half; ++j) {
                const int a = i + j, b = a + half, tw = j * stride;
                const float yr = re_[b] * twRe_[tw] - im_[b] * twIm_[tw];
                const float yi = re_[b] * twIm_[tw] + im_[b] * twRe_[tw];
                re_[b] = re_[a] - yr; im_[b] = im_[a] - yi;
                re_[a] += yr; im_[a] += yi;
            }
        }
    }
}

void SpectrumProcessor::process(const uint32_t* samples, SpectrumFrame& frame) {
    float meanI = 0, meanQ = 0;
    frame.clipped = 0;
    for (int i = 0; i < kSpectrumBins; ++i) {
        re_[i] = (float)signed10(samples[i]);
        // ESP32 mixing convention: negate Q so higher RF is to the right.
        im_[i] = -(float)signed10(samples[i] >> 10);
        if (fabsf(re_[i]) >= 511 || fabsf(im_[i]) >= 511) ++frame.clipped;
        meanI += re_[i]; meanQ += im_[i];
    }
    meanI /= kSpectrumBins; meanQ /= kSpectrumBins;
    for (int i = 0; i < kSpectrumBins; ++i) {
        re_[i] = (re_[i] - meanI) * window_[i];
        im_[i] = (im_[i] - meanQ) * window_[i];
    }
    fft();
    const float windowSum = (kSpectrumBins - 1) * 0.5f;
    const float norm = 512.0f * 512.0f * windowSum * windowSum;
    const bool useBurst = burstFilterEnabled_ && !raw_;
    if (useBurst && historyCount_ < kBurstFilterFrames) ++historyCount_;
    for (int i = 0; i < kSpectrumBins; ++i) {
        float power = (re_[i] * re_[i] + im_[i] * im_[i]) / norm;
        if (useBurst) {
            history_[historyHead_][i] = power;
            float ordered[kBurstFilterFrames];
            for (int j = 0; j < historyCount_; ++j) {
                const float value = history_[j][i];
                int insert = j;
                while (insert > 0 && ordered[insert - 1] > value) {
                    ordered[insert] = ordered[insert - 1];
                    --insert;
                }
                ordered[insert] = value;
            }
            // Lower middle during even-length startup; no zero-filled history.
            power = ordered[(historyCount_ - 1) / 2];
        }
        if (!primed_ || raw_) power_[i] = power;
        else power_[i] += kPowerAverageAlpha * (power - power_[i]);
        const float dbfs = 10.0f * log10f(fmaxf(power_[i], 1e-10f));
        int code = (int)((dbfs + 100.0f) * 255.0f / 100.0f);
        if (code < 0) code = 0;
        if (code > 255) code = 255;
        frame.bins[(i + kSpectrumBins / 2) % kSpectrumBins] = (uint8_t)code;
    }
    if (useBurst) historyHead_ = (historyHead_ + 1) % kBurstFilterFrames;
    primed_ = true;
    const int dc = kSpectrumBins / 2;
    frame.bins[dc] = (frame.bins[dc - 1] + frame.bins[dc + 1]) / 2;
    frame.valid = true;
    frame.burstFiltered = useBurst;
    frame.error[0] = '\0';
}
