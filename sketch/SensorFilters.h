#ifndef SENSOR_FILTERS_H
#define SENSOR_FILTERS_H

#include <Arduino.h>

// Sliding Median Filter for spike/bubble noise rejection
template<typename T, size_t WINDOW_SIZE>
class MedianFilter {
public:
    static_assert(WINDOW_SIZE % 2 == 1, "WINDOW_SIZE must be an odd number");

    MedianFilter() : m_head(0), m_count(0) {
        for (size_t i = 0; i < WINDOW_SIZE; ++i) {
            m_buffer[i] = 0;
        }
    }

    void addSample(T sample) {
        m_buffer[m_head] = sample;
        m_head = (m_head + 1) % WINDOW_SIZE;
        if (m_count < WINDOW_SIZE) {
            m_count++;
        }
    }

    T getMedian() const {
        if (m_count == 0) return 0;
        
        T sorted[WINDOW_SIZE];
        for (size_t i = 0; i < m_count; ++i) {
            sorted[i] = m_buffer[i];
        }

        // Insertion sort on small array
        for (size_t i = 1; i < m_count; ++i) {
            T key = sorted[i];
            int j = (int)i - 1;
            while (j >= 0 && sorted[j] > key) {
                sorted[j + 1] = sorted[j];
                j--;
            }
            sorted[j + 1] = key;
        }

        return sorted[m_count / 2];
    }

    void reset() {
        m_head = 0;
        m_count = 0;
    }

private:
    T m_buffer[WINDOW_SIZE];
    size_t m_head;
    size_t m_count;
};

// Exponential Moving Average (EMA) filter for continuous signal smoothing
class LowPassFilter {
public:
    explicit LowPassFilter(float alpha = 0.2f, float initialValue = 0.0f)
        : m_alpha(alpha), m_filteredValue(initialValue), m_initialized(false) {}

    float update(float currentSample) {
        if (!m_initialized) {
            m_filteredValue = currentSample;
            m_initialized = true;
            return m_filteredValue;
        }
        m_filteredValue = (m_alpha * currentSample) + ((1.0f - m_alpha) * m_filteredValue);
        return m_filteredValue;
    }

    float getValue() const {
        return m_filteredValue;
    }

    void reset() {
        m_initialized = false;
    }

private:
    float m_alpha;
    float m_filteredValue;
    bool m_initialized;
};

// 64-sample burst oversampling function on STM32 ADC
inline int readOversampledADC(int pin, int numSamples = 64) {
    uint32_t accumulator = 0;
    for (int i = 0; i < numSamples; ++i) {
        accumulator += analogRead(pin);
        delayMicroseconds(100); // 10 kHz sampling frequency spreads across 50/60Hz AC noise
    }
    return (int)(accumulator / numSamples);
}

#endif // SENSOR_FILTERS_H
