// data capture from the RTL-SDR device at 2 MHz sample rate and 1090 MHz frequency
// suitable for ADS-B signals used in dump1090
#include <iostream> 
#include <cstdio> 
#include <cstdlib> // for EXIT_SUCCESS and EXIT_FAILURE
#include <cstring> // for memset()
#include <ctime> // for time functions
#include <chrono>     // for high-resolution timing
#include <rtl-sdr.h>
#include <fcntl.h>      // For O_WRONLY | O_NONBLOCK
#include <errno.h>
#include <thread>
#include <unistd.h>  //for write(), close(), ssize_t
//#include <sys/stat.h> // for mkfifo (not used as FIFO creation is handled in launcher script)


#define DEFAULT_SAMPLE_RATE   2000000   // 2 MHz for dump1090 suitable ADS-B
#define DEFAULT_FREQUENCY     1090000000  // 1090 MHz (ADS-B)
#define CAPTURE_DURATION_SEC  10           // Capture time in seconds
#define TOTAL_SAMPLES         (CAPTURE_DURATION_SEC * DEFAULT_SAMPLE_RATE) // Total samples to capture
#define TOTAL_BYTES           ((size_t)CAPTURE_DURATION_SEC * DEFAULT_SAMPLE_RATE * 2) //   Total bytes captured (I+Q for each sample)
#define BUFFER_LENGTH         (256 * 1024)  // buffer of 256 KB chunks

int main() {
    const char *fifo_path = "/tmp/iq_pipe";
    // --- Create FIFO if missing --- //(no need for this block as its implemented in launcher script)
    // if (access(fifo_path, F_OK) != 0) {
    //     if (mkfifo(fifo_path, 0644) != 0) {
    //         perror("Failed to create FIFO");
    //     } 
    //     else {
    //         std::cout << "FIFO created: " << fifo_path << std::endl;
    //     }
    // }
    // Create unique filename with timestamp in milliseconds

    rtlsdr_dev_t *dev = nullptr; // Pointer to RTL-SDR device structure
    int device_count = rtlsdr_get_device_count(); // Get number of RTL-SDR devices connected
    
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
    if (rtlsdr_set_center_freq(dev, DEFAULT_FREQUENCY) < 0) {
     std::cerr << "Failed to set frequency." << std::endl;
     rtlsdr_close(dev); 
     return EXIT_FAILURE;
    }
    if (rtlsdr_set_sample_rate(dev, DEFAULT_SAMPLE_RATE) < 0) {
     std::cerr << "Failed to set sample rate." << std::endl;
     rtlsdr_close(dev); 
     return EXIT_FAILURE;
    }
    //rtlsdr_set_center_freq(dev, DEFAULT_FREQUENCY); // Set center frequency to 1090 MHz
    //rtlsdr_set_sample_rate(dev, DEFAULT_SAMPLE_RATE); // Set sample rate to 2 MHz

    rtlsdr_set_tuner_gain_mode(dev, 1); // Manual gain
    rtlsdr_set_tuner_gain(dev, 450); // gain of 45.0 dB
    rtlsdr_set_agc_mode(dev, 0); // Disable AGC (Automatic Gain Control) 
    rtlsdr_reset_buffer(dev); // Reset the internal buffer
    // After rtlsdr_reset_buffer(dev):
    std::this_thread::sleep_for(std::chrono::milliseconds(200)); // USB settle time
    
    std::cout << "Tuned to " << DEFAULT_FREQUENCY / 1e6 << " MHz, "
              << "Sample Rate = " << DEFAULT_SAMPLE_RATE / 1e6 << " MHz" << std::endl;

    // Create unique filename with timestamp in milliseconds
    auto now = std::chrono::system_clock::now(); // Get current time
    auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>( // Get milliseconds part of current time
        now.time_since_epoch()) % 1000; //  Modulo 1000 to get milliseconds
    time_t now_t = std::chrono::system_clock::to_time_t(now); // Convert to standard time (time_t)
    struct tm *t = localtime(&now_t); // Convert to local time structure
    
    char filename[128];
    snprintf(filename, sizeof(filename),  // Format filename with date and time with milliseconds
             "captures/iq_samples_%04d%02d%02d_%02d%02d%02d_%03d.bin",
             t->tm_year + 1900, t->tm_mon + 1, t->tm_mday,
             t->tm_hour, t->tm_min, t->tm_sec, 
             (int)now_ms.count());
    
    
    FILE *fp = fopen(filename, "wb"); // Keep file logging
    if (!fp) {
        std::cerr << "Failed to open output file." << std::endl;
        rtlsdr_close(dev);
        return EXIT_FAILURE;
    }



    // Open FIFO in non-blocking mode — retry for up to 5 seconds if no reader yet
    int fifo_fd = -1;
    for (int attempt = 0; attempt < 50; attempt++) {
     fifo_fd = open("/tmp/iq_pipe", O_WRONLY | O_NONBLOCK);
     if (fifo_fd >= 0) {
        std::cout << "FIFO opened for writing." << std::endl;
        // Set pipe buffer size once here
        fcntl(fifo_fd, F_SETPIPE_SZ, 1 * 1024 * 1024);
        int actual = fcntl(fifo_fd, F_GETPIPE_SZ);
        std::cout << "FIFO pipe buffer: " << actual / 1024 << " KB" << std::endl;
        break;
      }
     if (errno == ENXIO) {
        // No reader yet — wait and retry
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      } 
     else {
        perror("Failed to open FIFO");
        break;
      }
    }
    if (fifo_fd < 0) {
     std::cerr << "No reader on FIFO after retries. Writing .bin only." << std::endl;
    }
    std::cout << "Target: " << TOTAL_SAMPLES << " samples ("  // display target samples and bytes
              << TOTAL_BYTES / 1024.0 / 1024.0 << " MB)" << std::endl; // display total bytes that will be captured
    std::cout << "Capturing..." << std::endl; // Indicate start of capture
    
    unsigned char *buffer = new unsigned char[BUFFER_LENGTH]; // Allocate buffer for reading samples
    int n_read = 0; // Number of bytes read
    size_t total_bytes_captured = 0; // stores total bytes captured
    // size_t -> an unsigned data type meant for memory sizes and counts
    
    int dropped_chunks = 0; // Counter for dropped chunks when FIFO is full
    size_t dropped_bytes = 0;

    auto start_time = std::chrono::steady_clock::now(); // Start time for capture duration measurement
    
    while (total_bytes_captured < TOTAL_BYTES) { // Continue until total bytes captured reaches target
        // condition ? value_if_true : value_if_false
        size_t bytes_to_read = TOTAL_BYTES - total_bytes_captured;
        if (bytes_to_read > BUFFER_LENGTH) bytes_to_read = BUFFER_LENGTH;

        // force multiple of 512
        bytes_to_read &= ~511;
        // rtlsdr_read_sync: 
        // dev: pointer to opened RTL-SDR device.
        // buf: pointer to buffer where I/Q samples will be stored. 
        // len: number of bytes to read. This length must be a multiple of 512 and is typically the size of the buffer. 
        // n_read: A pointer to an integer that will store the number of bytes actually read. 
        if (rtlsdr_read_sync(dev, buffer, bytes_to_read, &n_read) < 0) {
            std::cerr << "Read failed." << std::endl;
            break;
        }
        
        if (n_read > 0) {
          // Always write to disk
          if (fwrite(buffer, 1, n_read, fp) != (size_t)n_read) {
            std::cerr << "Disk write failed — disk full?" << std::endl;
            break;
          }
          // Write to FIFO if open — write in small chunks to avoid partial writes
          if (fifo_fd >= 0) {
           size_t fifo_offset = 0;
           while (fifo_offset < (size_t)n_read) {
           // Write max 65536 bytes at a time (stays within pipe buffer)
            size_t to_write = std::min((size_t)n_read - fifo_offset, (size_t)65536);
            ssize_t written = write(fifo_fd, buffer + fifo_offset, to_write);

            if (written < 0) {
             if (errno == EAGAIN) {
                // FIFO full — decoder too slow, drop remainder of this buffer
                dropped_chunks++;
                dropped_bytes += (n_read - fifo_offset);
                break;
             } 
             else {
                perror("FIFO write error");
                break;
             }
           } 
            else {
             fifo_offset += written;
            }
          }
        }

          total_bytes_captured += n_read;
       }
    } // end while loop when total_bytes_captured >= TOTAL_BYTES
    
    auto end_time = std::chrono::steady_clock::now(); // End time for capture duration measurement
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count(); // Get elapsed time in milliseconds
    // time diff between start and end is calculated then the count() method converts duration to integer milliseconds
    // Cleanup
    // Close FIFO if it was opened
    if (fifo_fd >= 0) close(fifo_fd);
    // Close the file and free resources (your existing cleanup)
    fclose(fp); 
    delete[] buffer;
    rtlsdr_close(dev);
    
    std::cout << "\n=== Capture Complete ===" << std::endl; // Indicate capture completion
    std::cout << "Saved to: " << filename << std::endl; // Display output filename
    std::cout << "Total bytes: " << total_bytes_captured << " ("  // display total bytes captured (in MB)
              << total_bytes_captured / 1024.0 / 1024.0 << " MB)" << std::endl; 
    std::cout << "Total samples: " << total_bytes_captured / 2 << std::endl; // display total bytes used for captured samples (I+Q is taken as one sample)
    std::cout << "Duration: " << elapsed_ms / 1000.0 << " seconds" << std::endl; // display capture duration in seconds
    
    std::cout << "Dropped FIFO chunks: " << dropped_chunks << std::endl;
    std::cout << "Dropped FIFO bytes:  " << dropped_bytes 
          << " (" << dropped_bytes / 1024.0 / 1024.0 << " MB)" << std::endl;
    return EXIT_SUCCESS;
}
