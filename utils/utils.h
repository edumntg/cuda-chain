#include <iostream>
#include <string>
#include <openssl/sha.h>

#ifndef UTILS_H
#define UTILS_H

std::string hash_str(const std::string& input) {
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256_CTX sha256;
    SHA256_Init(&sha256);
    SHA256_Update(&sha256, input.c_str(), input.size());
    SHA256_Final(hash, &sha256);

    // Convert the hash to a hexadecimal string
    std::string output = "";
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        char hex[3];
        sprintf(hex, "%02x", hash[i]);
        output += hex;
    }
    return output;
}

#endif //UTILS_H
