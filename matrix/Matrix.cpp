//
// Created by Eduardo Montilva on 1/9/24.
//

#include "Matrix.h"
#include <chrono>

Matrix::Matrix(int rows, int columns): logger_("Matrix") {
    rows_ = rows;
    columns_ = columns;
    data_ = new double *[rows];
    for (int i = 0; i < rows; i++) {
        data_[i] = new double[columns];
    }
}

Matrix Matrix::from_array(double** array) {
    int rows = sizeof(array);
    int columns = sizeof(array[0]);
    Matrix matrix(rows, columns);
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < columns; j++) {
            matrix.set(i, j, array[i][j]);
        }
    }
    return matrix;
}

Matrix Matrix::from_json(nlohmann::json obj) {
    int rows = obj.size();
    int cols = obj[0].size();

    // Allocate memory for the 2D array
    auto** result = new double*[rows];
    for (int i = 0; i < rows; ++i) {
        result[i] = new double[cols];
    }

    // Copy the values into the 2D array
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            result[i][j] = obj[i][j];
        }
    }

    return from_array(result);
}


Matrix Matrix::zeros(int rows, int columns) {
    Matrix matrix(rows, columns);
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < columns; j++) {
            matrix.set(i, j, 0.0);
        }
    }
    return matrix;
}

Matrix Matrix::ones(int rows, int columns) {
    Matrix matrix(rows, columns);
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < columns; j++) {
            matrix.set(i, j, 1.0);
        }
    }
    return matrix;
}

int Matrix::get_rows() {
    return rows_;
}

int Matrix::get_columns() {
    return columns_;
}

int Matrix::get_data() {
    return **data_;
}

double Matrix::get(int i, int j) {
    return data_[i][j];
}

void Matrix::set(int i, int j, double value) {
    data_[i][j] = value;
}

double* Matrix::get_row(int i) {
    return data_[i];
}

double* Matrix::get_column(int j) {
    double* column = new double[rows_];
    for (int i = 0; i < rows_; i++) {
        column[i] = data_[i][j];
    }
    return column;
}

void Matrix::set_row(int i, double* row) {
    for (int j = 0; j < columns_; j++) {
        data_[i][j] = row[j];
    }
}

void Matrix::set_column(int j, double* column) {
    for (int i = 0; i < rows_; i++) {
        data_[i][j] = column[i];
    }
}

Matrix Matrix::add(Matrix matrix) {
    Matrix result(rows_, columns_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(i, j, data_[i][j] + matrix.get(i, j));
        }
    }
    return result;
}

Matrix Matrix::subtract(Matrix matrix) {
    Matrix result(rows_, columns_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(i, j, data_[i][j] - matrix.get(i, j));
        }
    }
    return result;
}

Matrix Matrix::multiply(Matrix matrix) {
    // const auto start = std::chrono::high_resolution_clock::now();
    Matrix result(rows_, matrix.get_columns());
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < matrix.get_columns(); j++) {
            double sum = 0.0;
            for (int k = 0; k < columns_; k++) {
                sum += data_[i][k] * matrix.get(k, j);
            }
            result.set(i, j, sum);
        }
    }
    // const auto end = std::chrono::high_resolution_clock::now();
    // const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    // logger_.info() << "Multiplication (" << std::to_string(get_rows()) << ", " << std::to_string(get_columns()) << ") x ("
    //                << std::to_string(matrix.get_rows()) << ", " << std::to_string(matrix.get_columns()) << ") took "
    //                << std::to_string(elapsed) << " ms" << std::endl;
    return result;
}

Matrix Matrix::divide(Matrix matrix) {
    Matrix result(rows_, columns_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(i, j, data_[i][j] / matrix.get(i, j));
        }
    }
    return result;
}

Matrix Matrix::transpose() {
    Matrix result(columns_, rows_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(j, i, data_[i][j]);
        }
    }
    return result;
}

Matrix Matrix::dot(Matrix matrix) {
    Matrix result(rows_, columns_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(i, j, data_[i][j] * matrix.get(i, j));
        }
    }
    return result;
}

Matrix Matrix::cross(Matrix matrix) {
    Matrix result(rows_, columns_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(i, j, data_[i][j] * matrix.get(i, j));
        }
    }
    return result;
}

Matrix Matrix::inverse() {
    Matrix result(rows_, columns_);
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(i, j, 1.0 / data_[i][j]);
        }
    }
    return result;
}

Matrix Matrix::reshape(int rows, int columns) {
    Matrix result(rows, columns);
    int k = 0;
    for (int i = 0; i < rows; i++) {
        for (int j = 0; j < columns; j++) {
            result.set(i, j, data_[k / columns][k % columns]);
            k++;
        }
    }
    return result;
}

Matrix Matrix::flatten() {
    Matrix result(1, rows_ * columns_);
    int k = 0;
    for (int i = 0; i < rows_; i++) {
        for (int j = 0; j < columns_; j++) {
            result.set(0, k, data_[i][j]);
            k++;
        }
    }
    return result;
}

