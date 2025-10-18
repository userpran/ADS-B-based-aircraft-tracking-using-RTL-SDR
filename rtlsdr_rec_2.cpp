#include <iostream>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <chrono>
#include <unistd.h>  // for access()
#include <rtl-sdr.h>

#define DEFAULT_SAMPLE_RATE   2000000
#define DEFAULT_FREQUENCY     1090000000
#define CAPTURE_DURATION_SEC  5
#define TOTAL_SAMPLES         (CAPTURE_DURATION_SEC * DEFAULT_SAMPLE_RATE)
#define TOTAL_BYTES           (TOTAL_SAMPLES * 2)
#define BUFFER_LENGTH         (256 * 1024)  // 256 KB chunks

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
    rtlsdr_set_tuner_gain_mode(dev, 1);
    rtlsdr_set_tuner_gain(dev, 450);
    rtlsdr_set_agc_mode(dev, 0);
    rtlsdr_reset_buffer(dev);
    
    std::cout << "Tuned to " << DEFAULT_FREQUENCY / 1e6 << " MHz, "
              << "Sample Rate = " << DEFAULT_SAMPLE_RATE / 1e6 << " MHz" << std::endl;
    
    // Create unique filename with milliseconds
    auto now = std::chrono::system_clock::now();
    auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;
    time_t now_t = std::chrono::system_clock::to_time_t(now);
    struct tm *t = localtime(&now_t);
    
    char filename[64];
    snprintf(filename, sizeof(filename), 
             "iq_samples_%04d%02d%02d_%02d%02d%02d_%03d.bin",
             t->tm_year + 1900, t->tm_mon + 1, t->tm_mday,
             t->tm_hour, t->tm_min, t->tm_sec, 
             (int)now_ms.count());
    
    FILE *fp = fopen(filename, "wb");
    if (!fp) {
        std::cerr << "Failed to open output file." << std::endl;
        rtlsdr_close(dev);
        return EXIT_FAILURE;
    }
    
    std::cout << "Target: " << TOTAL_SAMPLES << " samples (" 
              << TOTAL_BYTES / 1024.0 / 1024.0 << " MB)" << std::endl;
    std::cout << "Capturing..." << std::endl;
    
    unsigned char *buffer = new unsigned char[BUFFER_LENGTH];
    int n_read = 0;
    size_t total_bytes = 0;
    
    auto start_time = std::chrono::steady_clock::now();
    
    while (total_bytes < TOTAL_BYTES) {
        size_t bytes_to_read = (TOTAL_BYTES - total_bytes) < BUFFER_LENGTH 
                               ? (TOTAL_BYTES - total_bytes) 
                               : BUFFER_LENGTH;
        
        if (rtlsdr_read_sync(dev, buffer, bytes_to_read, &n_read) < 0) {
            std::cerr << "Read failed." << std::endl;
            break;
        }
        
        if (n_read > 0) {
            fwrite(buffer, 1, n_read, fp);
            total_bytes += n_read;
        }
    }
    
    auto end_time = std::chrono::steady_clock::now();
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        end_time - start_time).count();
    
    fclose(fp);
    delete[] buffer;
    rtlsdr_close(dev);
    
    std::cout << "\n=== Capture Complete ===" << std::endl;
    std::cout << "Saved to: " << filename << std::endl;
    std::cout << "Total bytes: " << total_bytes << " (" 
              << total_bytes / 1024.0 / 1024.0 << " MB)" << std::endl;
    std::cout << "Total samples: " << total_bytes / 2 << std::endl;
    std::cout << "Duration: " << elapsed_ms / 1000.0 << " seconds" << std::endl;
    
    return EXIT_SUCCESS;
}
