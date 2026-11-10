#include "InteriorFitLibrary.h"
#include "Components/LineBatchComponent.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/World.h"
#include "SceneManagement.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

bool UInteriorFitLibrary::DrawAreaPreview(UObject *WorldContext, const FString &JSON)
{
    if (!IsInGameThread() || !IsValid(WorldContext))
        return false;
    UWorld *World = WorldContext->GetWorld();
    if (!World || World->WorldType != EWorldType::Editor || !World->PersistentLineBatcher)
        return false;
    constexpr uint32 BatchID = 0x49464152;
    World->PersistentLineBatcher->ClearBatch(BatchID);
    if (JSON.IsEmpty())
    {
        if (GEditor)
            GEditor->RedrawLevelEditingViewports();
        return true;
    }
    TSharedPtr<FJsonObject> Data;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Data) || !Data)
        return false;
    const TArray<TSharedPtr<FJsonValue>> *Origin = nullptr;
    const TArray<TSharedPtr<FJsonValue>> *Cells = nullptr;
    double Step = 0;
    if (!Data->TryGetArrayField(TEXT("origin"), Origin) || Origin->Num() != 3 ||
        !Data->TryGetArrayField(TEXT("cells"), Cells) || Cells->Num() > 8192 ||
        !Data->TryGetNumberField(TEXT("cell_size"), Step) || !FMath::IsFinite(Step) || Step <= 0)
        return false;
    const FVector Offset((*Origin)[0]->AsNumber(), (*Origin)[1]->AsNumber(), (*Origin)[2]->AsNumber());
    if (Offset.ContainsNaN())
        return false;
    for (const auto &Value : *Cells)
    {
        const TArray<TSharedPtr<FJsonValue>> *Coordinates = nullptr;
        if (!Value->TryGetArray(Coordinates) || Coordinates->Num() != 3)
            return false;
        const FVector Center = Offset + FVector((*Coordinates)[0]->AsNumber(), (*Coordinates)[1]->AsNumber(),
                                                (*Coordinates)[2]->AsNumber());
        if (Center.ContainsNaN())
            return false;
        World->PersistentLineBatcher->DrawBox(Center, FVector(Step / 2, Step / 2, 2), FLinearColor(0, 1, 1), 300,
                                              SDPG_Foreground, 1, BatchID);
    }
    if (GEditor)
        GEditor->RedrawLevelEditingViewports();
    return true;
}

bool UInteriorFitLibrary::DrawSplinePreview(UObject *WorldContext, const TArray<FVector> &Points, bool Closed,
                                            bool OverBudget)
{
    if (!IsInGameThread() || !IsValid(WorldContext))
        return false;
    UWorld *World = WorldContext->GetWorld();
    if (!World || World->WorldType != EWorldType::Editor || !World->PersistentLineBatcher)
        return false;
    constexpr uint32 BatchID = 0x49465350;
    World->PersistentLineBatcher->ClearBatch(BatchID);
    if (Points.Num() > 8192)
        return false;
    for (const FVector &Point : Points)
        if (Point.ContainsNaN())
            return false;
    const FLinearColor Color = OverBudget ? FLinearColor(1, .15f, .05f) : FLinearColor(0, 1, 1);
    const int32 Segments = Closed ? Points.Num() : FMath::Max(0, Points.Num() - 1);
    for (int32 Index = 0; Index < Points.Num(); ++Index)
    {
        const FVector Position = Points[Index] + FVector(0, 0, 4);
        World->PersistentLineBatcher->DrawBox(Position, FVector(8), Color, 300, SDPG_Foreground, 1, BatchID);
        if (Index < Segments)
            World->PersistentLineBatcher->DrawLine(Position, Points[(Index + 1) % Points.Num()] + FVector(0, 0, 4),
                                                   Color, SDPG_Foreground, 2, 300, BatchID);
    }
    if (GEditor)
        GEditor->RedrawLevelEditingViewports();
    return true;
}
