#pragma once

#include "CoreMinimal.h"

class AVolume;

namespace InteriorFitVolumeAuthoring
{
    AVolume* CreateBoxVolume(UObject* WorldContext, TSubclassOf<AVolume> VolumeClass,
                             FTransform Transform, FVector HalfExtent);
    void RefreshVolumeCollision(AVolume* Volume);
} // namespace InteriorFitVolumeAuthoring
