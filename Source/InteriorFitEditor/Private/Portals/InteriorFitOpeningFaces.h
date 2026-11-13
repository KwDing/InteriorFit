#pragma once

#include "CoreMinimal.h"

class AActor;
class AVolume;

namespace InteriorFitOpeningFaces
{
    FString GetVolumeFaces(AVolume* Volume);
    FString GetActorPanelFace(AActor* Actor);
} // namespace InteriorFitOpeningFaces
