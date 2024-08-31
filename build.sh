#!/bin/bash

# Create build directory with correct permissions
mkdir -p build
chmod 755 build

# Change to the build directory
cd build || exit

# Run CMake and make
cmake ..
make