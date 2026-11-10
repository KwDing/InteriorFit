#pragma once

#include "CoreMinimal.h"

namespace InteriorFitOpenings
{
    void Register();
    void Shutdown();
    bool Show(const FString& JSON);
}
