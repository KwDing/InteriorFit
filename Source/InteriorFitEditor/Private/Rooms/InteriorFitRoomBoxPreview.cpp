#include "InteriorFitRoomBoxPreview.h"

#include "InteriorFitEditorWorld.h"

#include "Components/LineBatchComponent.h"
#include "Engine/World.h"
#include "SceneManagement.h"

bool InteriorFitRoomBoxPreview::DrawPreview(UObject* WorldContext, FTransform Transform,
                                            FVector HalfExtent, FLinearColor Color)
{
    ULineBatchComponent* Lines = InteriorFitEditorWorld::GetPreviewLineBatcher(WorldContext);
    if (!Lines)
    {
        return false;
    }
    constexpr uint32 PreviewBatchID = 0x49464954;
    Lines->ClearBatch(PreviewBatchID);
    if (Transform.ContainsNaN() || HalfExtent.ContainsNaN() || HalfExtent.GetMin() <= 0.0)
    {
        return false;
    }
    constexpr float PreviewLifetimeSeconds = 300.0f;
    Lines->DrawBox(Transform.GetLocation(), HalfExtent, Transform.GetRotation(), Color,
                   PreviewLifetimeSeconds, SDPG_Foreground, 3.0f, PreviewBatchID);
    return true;
}
