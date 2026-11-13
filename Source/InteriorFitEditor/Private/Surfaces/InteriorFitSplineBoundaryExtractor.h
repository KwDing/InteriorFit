#pragma once

#include "CoreMinimal.h"

class AActor;

namespace InteriorFitSplineBoundaryExtractor
{
    FString ExtractPlanarBoundary(const TArray<AActor*>& Sources);
}
