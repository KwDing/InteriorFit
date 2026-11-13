#pragma once

#include "CoreMinimal.h"

class AVolume;

namespace InteriorFitBrushQueries
{
    int32 CountBrushTriangles(AVolume* Volume);
    bool ContainsPoint(AVolume* Volume, FVector Position);
} // namespace InteriorFitBrushQueries
