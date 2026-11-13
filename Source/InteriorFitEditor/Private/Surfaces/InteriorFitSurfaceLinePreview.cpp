#include "InteriorFitSurfaceLinePreview.h"

#include "InteriorFitEditorWorld.h"

#include "InteriorFitArea.h"

#include "Components/LineBatchComponent.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/World.h"
#include "SceneManagement.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
    // Bound temporary line-batcher data and lifetime in the editor viewport.
    constexpr int32 MaxLinePreviewPoints = 8192;
    constexpr float PreviewLifetimeSeconds = 300.0f;
} // namespace

bool InteriorFitSurfaceLinePreview::DrawAreaPreview(UObject* WorldContext, const FString& JSON)
{
    ULineBatchComponent* Lines = InteriorFitEditorWorld::GetPreviewLineBatcher(WorldContext);
    if (!Lines)
    {
        return false;
    }
    constexpr uint32 BatchID = 0x49464152;
    Lines->ClearBatch(BatchID);
    if (JSON.IsEmpty())
    {
        if (GEditor)
        {
            GEditor->RedrawLevelEditingViewports();
        }
        return true;
    }
    TSharedPtr<FJsonObject> Data;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Data) || !Data)
    {
        return false;
    }
    const TArray<TSharedPtr<FJsonValue>>* Origin = nullptr;
    const TArray<TSharedPtr<FJsonValue>>* Cells = nullptr;
    double Step = 0;
    if (!Data->TryGetArrayField(TEXT("origin"), Origin) || Origin->Num() != 3 ||
        !Data->TryGetArrayField(TEXT("cells"), Cells) ||
        Cells->Num() > AInteriorFitArea::MaxSurfaceCells ||
        !Data->TryGetNumberField(TEXT("cell_size"), Step) || !FMath::IsFinite(Step) || Step <= 0)
    {
        return false;
    }
    const FVector Offset((*Origin)[0]->AsNumber(), (*Origin)[1]->AsNumber(),
                         (*Origin)[2]->AsNumber());
    if (Offset.ContainsNaN())
    {
        return false;
    }
    for (const TSharedPtr<FJsonValue>& Value : *Cells)
    {
        const TArray<TSharedPtr<FJsonValue>>* Coordinates = nullptr;
        if (!Value->TryGetArray(Coordinates) || Coordinates->Num() != 3)
        {
            return false;
        }
        const FVector Center =
            Offset + FVector((*Coordinates)[0]->AsNumber(), (*Coordinates)[1]->AsNumber(),
                             (*Coordinates)[2]->AsNumber());
        if (Center.ContainsNaN())
        {
            return false;
        }
        Lines->DrawBox(Center, FVector(Step / 2, Step / 2, 2), FLinearColor(0, 1, 1),
                       PreviewLifetimeSeconds, SDPG_Foreground, 1, BatchID);
    }
    if (GEditor)
    {
        GEditor->RedrawLevelEditingViewports();
    }
    return true;
}

bool InteriorFitSurfaceLinePreview::DrawSplinePreview(UObject* WorldContext,
                                                      const TArray<FVector>& Points, bool bClosed,
                                                      bool bOverBudget)
{
    ULineBatchComponent* Lines = InteriorFitEditorWorld::GetPreviewLineBatcher(WorldContext);
    if (!Lines)
    {
        return false;
    }
    constexpr uint32 BatchID = 0x49465350;
    Lines->ClearBatch(BatchID);
    if (Points.Num() > MaxLinePreviewPoints)
    {
        return false;
    }
    for (const FVector& Point : Points)
    {
        if (Point.ContainsNaN())
        {
            return false;
        }
    }
    const FLinearColor Color = bOverBudget ? FLinearColor(1, .15f, .05f) : FLinearColor(0, 1, 1);
    const int32 Segments = bClosed ? Points.Num() : FMath::Max(0, Points.Num() - 1);
    for (int32 Index = 0; Index < Points.Num(); ++Index)
    {
        const FVector Position = Points[Index] + FVector(0, 0, 4);
        Lines->DrawBox(Position, FVector(8), Color, PreviewLifetimeSeconds, SDPG_Foreground, 1,
                       BatchID);
        if (Index < Segments)
        {
            Lines->DrawLine(Position, Points[(Index + 1) % Points.Num()] + FVector(0, 0, 4), Color,
                            SDPG_Foreground, 2, PreviewLifetimeSeconds, BatchID);
        }
    }
    if (GEditor)
    {
        GEditor->RedrawLevelEditingViewports();
    }
    return true;
}
