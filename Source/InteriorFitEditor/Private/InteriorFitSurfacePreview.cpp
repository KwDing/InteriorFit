#include "InteriorFitSurfacePreview.h"

#include "InteriorFitLibrary.h"
#include "Components/LineBatchComponent.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
    bool ReadPoint(const TSharedPtr<FJsonValue>& Value, FVector& OutPoint)
    {
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        if (!Value.IsValid() || !Value->TryGetArray(Values) || Values->Num() != 3) return false;
        double X, Y, Z;
        if (!(*Values)[0]->TryGetNumber(X) || !(*Values)[1]->TryGetNumber(Y) || !(*Values)[2]->TryGetNumber(Z)) return false;
        OutPoint = FVector(X, Y, Z);
        return !OutPoint.ContainsNaN();
    }
}

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
        UE_LOG(LogTemp, Warning, TEXT("Audio Auto Fit: invalid saved preview %s; delete it and preview the source surface again."), *GetActorLabel());
}

bool AInteriorFitSurfacePreview::InitializePreview(const FString& JSON)
{
    TSharedPtr<FJsonObject> Data;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Data) || !Data) return false;
    const TArray<TSharedPtr<FJsonValue>>* Sources = nullptr;
    if (!Data->TryGetArrayField(TEXT("sources"), Sources) || Sources->Num() > 128) return false;
    const TSharedPtr<FJsonObject>* Area = nullptr;
    const bool bArea = Data->TryGetObjectField(TEXT("data"), Area);
    const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
    FVector Origin = FVector::ZeroVector;
    double Step = 0;
    if (bArea)
    {
        const auto* OriginValue = (*Area)->Values.Find(TEXT("origin"));
        if (!OriginValue || !ReadPoint(*OriginValue, Origin) || !(*Area)->TryGetNumberField(TEXT("cell_size"), Step)
            || !FMath::IsFinite(Step) || Step <= 0 || !(*Area)->TryGetArrayField(TEXT("cells"), Values) || Values->Num() > 8192) return false;
    }
    else if (!Data->TryGetArrayField(TEXT("points"), Values) || Values->Num() > 256) return false;
    if (Values->IsEmpty()) return false;
    TArray<FVector> Points;
    for (const auto& Value : *Values)
    {
        FVector Point;
        if (!ReadPoint(Value, Point)) return false;
        Points.Add(Point + Origin);
    }
    Tags.AddUnique(TEXT("AudioAutoFitPreview"));
    for (const auto& Value : *Sources)
    {
        FString Path;
        if (!Value->TryGetString(Path)) return false;
        Tags.AddUnique(FName(TEXT("AudioAutoFitInput:") + Path));
    }
    FString Label, Shape;
    Data->TryGetStringField(TEXT("label"), Label);
    Data->TryGetStringField(TEXT("shape"), Shape);
    SetActorLabel(TEXT("PREVIEW__") + Label, false);
    const bool bRoom = Shape == TEXT("RoomCandidate");
    if (bRoom) SetFlags(RF_Transient);
    SetFolderPath(bRoom ? TEXT("InteriorFit/Review") : TEXT("Audio/Ambience"));
    Lines->Flush();
    const FLinearColor Color = bRoom ? FLinearColor(1.f, .36f, .01f) : FLinearColor(0, 1, 1);
    for (int32 Index = 0; Index < Points.Num(); ++Index)
    {
        if (!bRoom) Lines->DrawBox(Points[Index], bArea ? FVector(Step / 2, Step / 2, 2) : FVector(8), Color, 0, SDPG_Foreground, 1);
        if (!bArea && (Index + 1 < Points.Num() || Shape == TEXT("Lake")))
            Lines->DrawLine(Points[Index], Points[(Index + 1) % Points.Num()], Color, SDPG_Foreground, 2, 0);
    }
    PreviewJSON = JSON;
    return true;
}

AActor* UInteriorFitLibrary::CreateSurfacePreview(UObject* WorldContext, const FString& JSON)
{
    if (!IsInGameThread() || !IsValid(WorldContext) || !GEditor || GEditor->PlayWorld) return nullptr;
    UWorld* World = WorldContext->GetWorld();
    if (!World || World->WorldType != EWorldType::Editor) return nullptr;
    FActorSpawnParameters Parameters;
    Parameters.ObjectFlags = RF_DuplicateTransient;
    auto* Preview = World->SpawnActor<AInteriorFitSurfacePreview>(Parameters);
    if (!Preview) return nullptr;
    if (!Preview->InitializePreview(JSON)) { World->DestroyActor(Preview); return nullptr; }
    GEditor->RedrawLevelEditingViewports();
    return Preview;
}

bool UInteriorFitLibrary::ClearSurfacePreviews(UObject* WorldContext)
{
    if (!IsInGameThread() || !IsValid(WorldContext) || !GEditor || GEditor->PlayWorld) return false;
    UWorld* World = WorldContext->GetWorld();
    if (!World || World->WorldType != EWorldType::Editor) return false;
    TArray<AActor*> Previews;
    for (TActorIterator<AInteriorFitSurfacePreview> It(World); It; ++It) Previews.Add(*It);
    bool bCleared = true;
    for (AActor* Preview : Previews)
    {
        GEditor->SelectActor(Preview, false, false);
        if (!World->DestroyActor(Preview)) bCleared = false;
    }
    if (!Previews.IsEmpty()) GEditor->NoteSelectionChange();
    GEditor->RedrawLevelEditingViewports();
    return bCleared;
}
