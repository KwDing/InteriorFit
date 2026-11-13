#pragma once

#include "CoreMinimal.h"

class AActor;

namespace InteriorFitPreviewActors
{
    AActor* CreateSurfacePreview(UObject* WorldContext, const FString& JSON);
    bool ClearSurfacePreviews(UObject* WorldContext);
} // namespace InteriorFitPreviewActors
