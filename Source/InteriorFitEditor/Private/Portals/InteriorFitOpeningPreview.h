#pragma once

#include "CoreMinimal.h"

namespace InteriorFitOpeningPreview
{
    // Keep the native review JSON limit aligned with Python opening discovery.
    inline constexpr uint32 OpeningBatchID = 0x49464F50;
    inline constexpr int32 MaxReviewRows = 128;

    bool DrawOpeningPreviews(UObject* WorldContext, const FString& JSON);
} // namespace InteriorFitOpeningPreview
