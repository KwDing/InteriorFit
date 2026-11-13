#pragma once

#include "CoreMinimal.h"

class AActor;

namespace InteriorFitAreaSurfaceSampler
{
    FString SampleAreaSurface(const TArray<AActor*>& Sources, float RequestedCellSize,
                              bool bExcludeCoveredSurface);
}
