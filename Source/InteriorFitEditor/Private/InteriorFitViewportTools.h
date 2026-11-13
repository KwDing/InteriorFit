#pragma once

#include "CoreMinimal.h"

class AActor;

namespace InteriorFitViewportTools
{
    AActor* CreateViewportSeed();
    void FocusOpening(FVector Center, FVector HalfExtent);
} // namespace InteriorFitViewportTools
