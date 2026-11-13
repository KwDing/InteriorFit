#pragma once

#include "CoreMinimal.h"

namespace InteriorFitSurfaceLinePreview
{
    bool DrawAreaPreview(UObject* WorldContext, const FString& JSON);
    bool DrawSplinePreview(UObject* WorldContext, const TArray<FVector>& Points, bool bClosed,
                           bool bOverBudget);
} // namespace InteriorFitSurfaceLinePreview
