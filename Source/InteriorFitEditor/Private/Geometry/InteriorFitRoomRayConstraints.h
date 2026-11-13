#pragma once

#include "CoreMinimal.h"
#include "Engine/HitResult.h"

class AActor;

namespace InteriorFitRoomRayConstraints
{
    TArray<FHitResult> ConstrainRoomRays(const TArray<AActor*>& Rooms,
                                         const TArray<FVector>& Starts, const TArray<FVector>& Ends,
                                         const TArray<FHitResult>& PhysicalHits);
}
