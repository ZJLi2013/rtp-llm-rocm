#pragma once
#include "src/fastertransformer/core/Buffer.h"

#include <vector>
#include <algorithm>


namespace fastertransformer {

using Shape = std::vector<size_t>;

bool CheckShapeConsistent(const std::vector<Shape>& shape_list);

std::string ShapeStringView(const Shape& shape);

}  // namespace fastertransformer
