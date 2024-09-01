#pragma once
#include <iostream>
#include <string>
#include <ctime>
#include <chrono>
#include <sstream>

// Define a Logger class
class Logger {
public:
    // Constructor
    Logger(const std::string& className) : className_(className) {}

    // Log levels
    enum LogLevel {
        DEBUG,
        INFO,
        WARNING,
        ERROR
    };

    // Log methods
    Logger& debug() {
        logLevel_ = LogLevel::DEBUG;
        return *this;
    }

    Logger& info() {
        logLevel_ = LogLevel::INFO;
        return *this;
    }

    Logger& warning() {
        logLevel_ = LogLevel::WARNING;
        return *this;
    }

    Logger& error() {
        logLevel_ = LogLevel::ERROR;
        return *this;
    }

    // Overload the << operator to accept strings
    Logger& operator<<(const std::string& message) {
        logMessage_ += message;
        return *this;
    }

    // Overload the << operator to accept std::endl
    Logger& operator<<(std::ostream& (*pf)(std::ostream&)) {
        // Get the current date and time
        auto now = std::chrono::system_clock::now();
        auto now_time = std::chrono::system_clock::to_time_t(now);
        auto now_tm = *std::localtime(&now_time);

        // Create the log message
        std::string logMessage = "[";

        // Add the date
        char date[20];
        strftime(date, sizeof(date), "%Y-%m-%d", &now_tm);
        logMessage += date;

        // Add the time
        char time[20];
        strftime(time, sizeof(time), " %H:%M:%S", &now_tm);
        logMessage += time;

        // Add the class name
        logMessage += " " + className_ + "] ";

        // Add the log level
        switch (logLevel_) {
            case LogLevel::DEBUG:
                logMessage += "[DEBUG] ";
                break;
            case LogLevel::INFO:
                logMessage += "[INFO] ";
                break;
            case LogLevel::WARNING:
                logMessage += "[WARNING] ";
                break;
            case LogLevel::ERROR:
                logMessage += "[ERROR] ";
                break;
        }

        // Add the message
        logMessage += logMessage_;

        // Print the log message
        std::cout << logMessage << std::endl;

        // Reset the log message
        logMessage_.clear();

        return *this;
    }

private:
    std::string className_;
    LogLevel logLevel_;
    std::string logMessage_;
};