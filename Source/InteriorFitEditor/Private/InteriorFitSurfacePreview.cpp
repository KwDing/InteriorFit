#include "InteriorFitSurfacePreview.h"

#include "InteriorFitArea.h"
#include "InteriorFitEditorLog.h"

#include "Components/LineBatchComponent.h"
#include "SceneManagement.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
    // Limits for the actor preview payload, independent of sampling work.
    constexpr int32 MaxPreviewSources = 128;
    constexpr int32 MaxPreviewSplinePoints = 256;

    bool ReadPoint(const TSharedPtr<FJsonValue>& Value, FVector& OutPoint)
    {
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        if (!Value.IsValid() || !Value->TryGetArray(Values) || Values->Num() != 3)
        {
            return false;
        }
        double X, Y, Z;
        if (!(*Values)[0]->TryGetNumber(X) || !(*Values)[1]->TryGetNumber(Y) ||
            !(*Values)[2]->TryGetNumber(Z))
        {
            return false;
        }
        OutPoint = FVector(X, Y, Z);
        return !OutPoint.ContainsNaN();
    }
    constexpr double AreaPreviewHalfHeightCm = 2;
    constexpr double SplineMarkerHalfExtentCm = 8;

    bool ReadPoints(const TArray<TSharedPtr<FJsonValue>>* Values, int32 Limit,
                    const FVector& Origin, TArray<FVector>& Points)
    {
        if (!Values || Values->IsEmpty() || Values->Num() > Limit)
        {
            return false;
        }
        Points.Reserve(Values->Num());
        for (const TSharedPtr<FJsonValue>& Value : *Values)
        {
            FVector Point;
            if (!ReadPoint(Value, Point))
            {
                return false;
            }
            Points.Add(Point + Origin);
        }
        return true;
    }

    bool ReadArea(const FJsonObject& Area, TArray<FVector>& Points, double& Step)
    {
        const TSharedPtr<FJsonValue>* OriginValue = Area.Values.Find(TEXT("origin"));
        FVector Origin;
        if (!OriginValue || !ReadPoint(*OriginValue, Origin))
        {
            return false;
        }
        if (!Area.TryGetNumberField(TEXT("cell_size"), Step) || !FMath::IsFinite(Step) || Step <= 0)
        {
            return false;
        }
        const TArray<TSharedPtr<FJsonValue>>* Cells = nullptr;
        return Area.TryGetArrayField(TEXT("cells"), Cells) &&
               ReadPoints(Cells, AInteriorFitArea::MaxSurfaceCells, Origin, Points);
    }

    bool ReadSpline(const FJsonObject& Data, TArray<FVector>& Points)
    {
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        return Data.TryGetArrayField(TEXT("points"), Values) &&
               ReadPoints(Values, MaxPreviewSplinePoints, FVector::ZeroVector, Points);
    }
} // namespace

AInteriorFitSurfacePreview::AInteriorFitSurfacePreview()
{
    SetFlags(RF_DuplicateTransient);
    bIsEditorOnlyActor = true;
    bLockLocation = true;
    PrimaryActorTick.bCanEverTick = false;
    Lines = CreateDefaultSubobject<ULineBatchComponent>(TEXT("PreviewGeometry"));
    SetRootComponent(Lines);
    Lines->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    Lines->SetHiddenInGame(true);
    Lines->bCalculateAccurateBounds = true;
    Lines->PrimaryComponentTick.bCanEverTick = false;
}

void AInteriorFitSurfacePreview::PostLoad()
{
    Super::PostLoad();
    SetFlags(RF_DuplicateTransient);
    if (!PreviewJSON.IsEmpty() && !InitializePreview(PreviewJSON))
    {
        UE_LOG(LogInteriorFit, Warning,
               TEXT("Audio Auto Fit: invalid saved preview %s; delete it and preview the source "
                    "surface again."),
               *GetActorLabel());
    }
}

bool AInteriorFitSurfacePreview::InitializePreview(const FString& JSON)
{
    TSharedPtr<FJsonObject> Data;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Data) || !Data)
    {
        return false;
    }
    const TArray<TSharedPtr<FJsonValue>>* Sources = nullptr;
    if (!Data->TryGetArrayField(TEXT("sources"), Sources) || Sources->Num() > MaxPreviewSources)
    {
        return false;
    }
    const TSharedPtr<FJsonObject>* Area = nullptr;
    const bool bArea = Data->TryGetObjectField(TEXT("data"), Area);
    TArray<FVector> Points;
    double Step = 0;
    const bool bValidGeometry = bArea ? ReadArea(**Area, Points, Step) : ReadSpline(*Data, Points);
    if (!bValidGeometry)
    {
        return false;
    }
    Tags.AddUnique(TEXT("AudioAutoFitPreview"));
    for (const TSharedPtr<FJsonValue>& Value : *Sources)
    {
        FString Path;
        if (!Value->TryGetString(Path))
        {
            return false;
        }
        Tags.AddUnique(FName(TEXT("AudioAutoFitInput:") + Path));
    }
    FString Label, Shape;
    Data->TryGetStringField(TEXT("label"), Label);
    Data->TryGetStringField(TEXT("shape"), Shape);
    SetActorLabel(TEXT("PREVIEW__") + Label, false);
    const bool bRoom = Shape == TEXT("RoomCandidate");
    if (bRoom)
    {
        SetFlags(RF_Transient);
    }
    SetFolderPath(bRoom ? TEXT("InteriorFit/Review") : TEXT("Audio/Ambience"));
    Lines->Flush();
    const FLinearColor Color = bRoom ? FLinearColor(1.f, .36f, .01f) : FLinearColor(0, 1, 1);
    for (int32 Index = 0; Index < Points.Num(); ++Index)
    {
        if (!bRoom)
        {
            Lines->DrawBox(Points[Index],
                           bArea ? FVector(Step / 2, Step / 2, AreaPreviewHalfHeightCm)
                                 : FVector(SplineMarkerHalfExtentCm),
                           Color, 0, SDPG_Foreground, 1);
        }
        if (!bArea && (Index + 1 < Points.Num() || Shape == TEXT("Lake")))
        {
            Lines->DrawLine(Points[Index], Points[(Index + 1) % Points.Num()], Color,
                            SDPG_Foreground, 2, 0);
        }
    }
    PreviewJSON = JSON;
    return true;
}
