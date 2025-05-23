//
// Created by Eduardo Montilva on 1/9/24.
//

#ifndef MATRIX_H
#define MATRIX_H
#include <json.hpp>
#include <logger/Logger.h>

class Matrix {
private:
    int rows_;
    int columns_;
    double** data_;
    Logger logger_;

public:
    Matrix(int, int);
    ~Matrix();  // Already properly implemented
    static Matrix from_array(double**, int rows, int columns);  // Fixed signature
    static Matrix from_json(nlohmann::json);
    Matrix zeros(int, int);
    Matrix ones(int, int);
    int get_rows();
    int get_columns();
    int get_data();
    double get(int, int);
    void set(int, int, double);
    double* get_row(int);
    double* get_column(int);
    void set_row(int, double*);
    void set_column(int, double*);

   // Methods
   Matrix add(Matrix);
   Matrix subtract(Matrix);
   Matrix multiply(Matrix);
    Matrix divide(Matrix);
    Matrix transpose();
    Matrix dot(Matrix);
    Matrix cross(Matrix);
    Matrix inverse();
    Matrix reshape(int, int);
    Matrix flatten();


};



#endif //MATRIX_H
