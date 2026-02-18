#include <iostream>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <chrono>
#include <rtl-sdr.h>

// #define DEFAULT_SAMPLE_RATE   2400000   // 2.4 MHz for ADS-B
#define DEFAULT_SAMPLE_RATE   2000000   // 2 MHz for dump1090 suitable ADS-B 
#define DEFAULT_FREQUENCY     1090000000  // 1090 MHz (ADS-B)
#define DEFAULT_GAIN          0           // Auto
#define CAPTURE_DURATION_SEC  3           // Capture time in seconds

#define BUFFER_LENGTH         (CAPTURE_DURATION_SEC * DEFAULT_SAMPLE_RATE * 2)  //  bytes per read


int main() {
    rtlsdr_dev_t *dev = nullptr;

    int device_count = rtlsdr_get_device_count();
    if (device_count <= 0) {
        std::cerr << "No RTL-SDR devices found." << std::endl;
        return EXIT_FAILURE;
    }

    std::cout << "Found " << device_count << " device(s)." << std::endl;
    std::cout << "Using device 0: " << rtlsdr_get_device_name(0) << std::endl;

    if (rtlsdr_open(&dev, 0) < 0) {
        std::cerr << "Failed to open RTL-SDR device." << std::endl;
        return EXIT_FAILURE;
    }

    // Configure device
    rtlsdr_set_center_freq(dev, DEFAULT_FREQUENCY);
    rtlsdr_set_sample_rate(dev, DEFAULT_SAMPLE_RATE);
    rtlsdr_set_tuner_gain_mode(dev, 1);   // Manual gain
    rtlsdr_set_tuner_gain(dev, 450);      // 45.0 dB
    rtlsdr_reset_buffer(dev);

    std::cout << "Tuned to " << DEFAULT_FREQUENCY / 1e6 << " MHz, "
              << "Sample Rate = " << DEFAULT_SAMPLE_RATE / 1e6 << " MHz" << std::endl;

    // Create unique filename using timestamp
    time_t now = time(nullptr);
    struct tm *t = localtime(&now);
    char filename[64];
    strftime(filename, sizeof(filename), "iq_samples_%Y%m%d_%H%M%S.bin", t);

    FILE *fp = fopen(filename, "wb");
    if (!fp) {
        std::cerr << "Failed to open output file." << std::endl;
        rtlsdr_close(dev);
        return EXIT_FAILURE;
    }

    std::cout << "Capturing for " << CAPTURE_DURATION_SEC << " seconds..." << std::endl;

    unsigned char *buffer = new unsigned char[BUFFER_LENGTH];
    int n_read = 0;

    auto start_time = std::chrono::steady_clock::now();

    while (true) {
        if (rtlsdr_read_sync(dev, buffer, BUFFER_LENGTH, &n_read) < 0) {
            std::cerr << "Read failed." << std::endl;
            break;
        }

        if (n_read > 0) {
            fwrite(buffer, 1, n_read, fp);
        }

        // Check elapsed time
        auto elapsed = std::chrono::steady_clock::now() - start_time;
        if (std::chrono::duration_cast<std::chrono::seconds>(elapsed).count() >= CAPTURE_DURATION_SEC) {
            break;
        }
    }

    // Cleanup
    fclose(fp);
    delete[] buffer;
    rtlsdr_close(dev);

    std::cout << "Capture complete. Saved to: " << filename << std::endl;
    
    std::cout << "Last read details. " <<  n_read<< " bytes filled in the buffer of length" <<BUFFER_LENGTH<<std::endl;
    return EXIT_SUCCESS;
}


