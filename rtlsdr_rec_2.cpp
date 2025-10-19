// data capture from the RTL-SDR device at 2 MHz sample rate and 1090 MHz frequency

#include <iostream> 
#include <cstdio> 
#include <cstdlib> // for EXIT_SUCCESS and EXIT_FAILURE
#include <cstring> // for memset()
#include <ctime> // for time functions
#include <chrono>     // for high-resolution timing
#include <unistd.h>  // for access()
#include <rtl-sdr.h>

#define DEFAULT_SAMPLE_RATE   2000000   // 2 MHz for dump1090 suitable ADS-B
#define DEFAULT_FREQUENCY     1090000000  // 1090 MHz (ADS-B)
#define CAPTURE_DURATION_SEC  5           // Capture time in seconds
#define TOTAL_SAMPLES         (CAPTURE_DURATION_SEC * DEFAULT_SAMPLE_RATE) // Total samples to capture
#define TOTAL_BYTES           (TOTAL_SAMPLES * 2) //   Total bytes captured (I+Q for each sample)
#define BUFFER_LENGTH         (256 * 1024)  // buffer of 256 KB chunks

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
    rtlsdr_set_center_freq(dev, DEFAULT_FREQUENCY); // Set center frequency to 1090 MHz
    rtlsdr_set_sample_rate(dev, DEFAULT_SAMPLE_RATE); // Set sample rate to 2 MHz
    rtlsdr_set_tuner_gain_mode(dev, 1); // Manual gain
    rtlsdr_set_tuner_gain(dev, 450); // gain of 45.0 dB
    rtlsdr_set_agc_mode(dev, 0); // Disable AGC (Automatic Gain Control) 
    rtlsdr_reset_buffer(dev); // Reset the internal buffer
    
    std::cout << "Tuned to " << DEFAULT_FREQUENCY / 1e6 << " MHz, "
              << "Sample Rate = " << DEFAULT_SAMPLE_RATE / 1e6 << " MHz" << std::endl;
    
    // Create unique filename with timestamp in milliseconds
    auto now = std::chrono::system_clock::now(); // Get current time
    auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>( // Get milliseconds part of current time
        now.time_since_epoch()) % 1000; //  Modulo 1000 to get milliseconds
    time_t now_t = std::chrono::system_clock::to_time_t(now); // Convert to standard time (time_t)
    struct tm *t = localtime(&now_t); // Convert to local time structure
    
    char filename[64];
    snprintf(filename, sizeof(filename),  // Format filename with date and time with milliseconds
             "iq_samples_%04d%02d%02d_%02d%02d%02d_%03d.bin",
             t->tm_year + 1900, t->tm_mon + 1, t->tm_mday,
             t->tm_hour, t->tm_min, t->tm_sec, 
             (int)now_ms.count());
    
    FILE *fp = fopen(filename, "wb");
    if (!fp) {
        std::cerr << "Failed to open output file." << std::endl; // Error if file cannot be opened
        rtlsdr_close(dev); // Close RTL-SDR device
        return EXIT_FAILURE; // Exit with failure
    }
    
    std::cout << "Target: " << TOTAL_SAMPLES << " samples ("  // display target samples and bytes
              << TOTAL_BYTES / 1024.0 / 1024.0 << " MB)" << std::endl; // display total bytes that will be captured
    std::cout << "Capturing..." << std::endl; // Indicate start of capture
    
    unsigned char *buffer = new unsigned char[BUFFER_LENGTH]; // Allocate buffer for reading samples
    int n_read = 0; // Number of bytes read
    size_t total_bytes_captured = 0; // stores total bytes captured
    // size_t -> an unsigned data type meant for memory sizes and counts
    
    auto start_time = std::chrono::steady_clock::now(); // Start time for capture duration measurement
    
    while (total_bytes_captured < TOTAL_BYTES) { // Continue until total bytes captured reaches target
        // condition ? value_if_true : value_if_false
        size_t bytes_to_read = ((TOTAL_BYTES - total_bytes_captured) < BUFFER_LENGTH ) // bytes_to_read will be given value based on this condition
                               ? (TOTAL_BYTES - total_bytes_captured) 
                               : BUFFER_LENGTH;
        // rtlsdr_read_sync: 
        // dev: pointer to opened RTL-SDR device.
        // buf: pointer to buffer where I/Q samples will be stored. 
        // len: number of bytes to read. This length must be a multiple of 512 and is typically the size of the buffer. 
        // n_read: A pointer to an integer that will store the number of bytes actually read. 
        if (rtlsdr_read_sync(dev, buffer, bytes_to_read, &n_read) < 0) {
            std::cerr << "Read failed." << std::endl;
            break;
        }
        
        if (n_read > 0) { // If bytes were read successfully
            fwrite(buffer, 1, n_read, fp); // Write the read samples to the output file
            total_bytes_captured += n_read; // updates total bytes captured
        }
    } // end while loop when total_bytes_captured >= TOTAL_BYTES
    
    auto end_time = std::chrono::steady_clock::now(); // End time for capture duration measurement
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count(); // Get elapsed time in milliseconds
    // time diff between start and end is calculated then the count() method converts duration to integer milliseconds
    // Cleanup
    fclose(fp);
    delete[] buffer;
    rtlsdr_close(dev);
    
    std::cout << "\n=== Capture Complete ===" << std::endl; // Indicate capture completion
    std::cout << "Saved to: " << filename << std::endl; // Display output filename
    std::cout << "Total bytes: " << total_bytes_captured << " ("  // display total bytes captured (in MB)
              << total_bytes_captured / 1024.0 / 1024.0 << " MB)" << std::endl; 
    std::cout << "Total samples: " << total_bytes_captured / 2 << std::endl; // display total bytes used for captured samples (I+Q is taken as one sample)
    std::cout << "Duration: " << elapsed_ms / 1000.0 << " seconds" << std::endl; // display capture duration in seconds
    
    return EXIT_SUCCESS;
}
