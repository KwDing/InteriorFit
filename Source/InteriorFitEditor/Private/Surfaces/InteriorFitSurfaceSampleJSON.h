#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

namespace InteriorFitSurfaceSampleJSON
{
    FString Encode(const TSharedRef<FJsonObject>& Data);
    FString Fail(const FString& Message);
    TArray<TSharedPtr<FJsonValue>> VectorJSON(const FVector& Value);
} // namespace InteriorFitSurfaceSampleJSON
