#include "InteriorFitOpeningPreview.h"

#include "InteriorFitEditorWorld.h"

#include "Components/LineBatchComponent.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/World.h"
#include "SceneManagement.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
    FVector ReadVector(const TSharedPtr<FJsonObject>& Object, const FString& Key)
    {
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        if (!Object->TryGetArrayField(Key, Values) || Values->Num() != 3)
        {
            return FVector::ZeroVector;
        }
        return FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(),
                       (*Values)[2]->AsNumber());
    }
} // namespace

bool InteriorFitOpeningPreview::DrawOpeningPreviews(UObject* WorldContext, const FString& JSON)
{
    ULineBatchComponent* Lines = InteriorFitEditorWorld::GetPreviewLineBatcher(WorldContext);
    if (!Lines)
    {
        return false;
    }
    constexpr float PreviewLifetimeSeconds = 300.0f;
    Lines->ClearBatch(OpeningBatchID);
    TArray<TSharedPtr<FJsonValue>> Rows;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Rows) ||
        Rows.Num() > MaxReviewRows)
    {
        return false;
    }
    for (const TSharedPtr<FJsonValue>& Value : Rows)
    {
        const TSharedPtr<FJsonObject> Row = Value->AsObject();
        if (!Row.IsValid())
        {
            continue;
        }
        const FVector Center = ReadVector(Row, TEXT("center"));
        const FVector Extent = ReadVector(Row, TEXT("half_extent"));
        double Yaw = 0.0;
        Row->TryGetNumberField(TEXT("yaw"), Yaw);
        if (Center.ContainsNaN() || Extent.ContainsNaN() || Extent.GetMin() <= 0.0 ||
            !FMath::IsFinite(Yaw))
        {
            continue;
        }
        bool bOpen = false;
        Row->TryGetBoolField(TEXT("open"), bOpen);
        const FLinearColor Color = bOpen ? FLinearColor::Green : FLinearColor(1.0f, 0.6f, 0.0f);
        Lines->DrawBox(Center, Extent, FRotator(0.0, Yaw, 0.0).Quaternion(), Color,
                       PreviewLifetimeSeconds, SDPG_Foreground, 2.0f, OpeningBatchID);
    }
    if (GEditor)
    {
        GEditor->RedrawLevelEditingViewports();
    }
    return true;
}
