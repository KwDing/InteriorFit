#include "InteriorFitLibrary.h"
#include "BSPOps.h"
#include "Components/BrushComponent.h"

#include "ActorFactories/ActorFactory.h"
#include "Builders/CubeBuilder.h"
#include "Components/LineBatchComponent.h"
#include "Engine/World.h"
#include "GameFramework/Volume.h"
#include "Model.h"
#include "SceneManagement.h"
#include "Engine/Polys.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "InteriorFitOpeningsPanel.h"
#include "Editor.h"
#include "LevelEditorViewport.h"
#include "Engine/TargetPoint.h"

namespace
{
    TArray<TSharedPtr<FJsonValue>> VectorValues(const FVector& Value)
    {
        return {MakeShared<FJsonValueNumber>(Value.X), MakeShared<FJsonValueNumber>(Value.Y), MakeShared<FJsonValueNumber>(Value.Z)};
    }

    FVector ReadVector(const TSharedPtr<FJsonObject>& Object, const FString& Key)
    {
        const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
        if (!Object->TryGetArrayField(Key, Values) || Values->Num() != 3) return FVector::ZeroVector;
        return FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
    }
}

AActor* UInteriorFitLibrary::CreateViewportSeed()
{
    if (!GEditor || GEditor->PlayWorld || !GCurrentLevelEditingViewportClient) return nullptr;
    auto* View = GCurrentLevelEditingViewportClient;
    UWorld* World = GEditor->GetEditorWorldContext().World();
    if (!World || View->GetWorld() != World || !View->IsPerspective()) return nullptr;

    const FVector Position = View->GetViewLocation();
    FActorSpawnParameters Spawn;
    Spawn.ObjectFlags = RF_Transient;
    Spawn.bCreateActorPackage = false;
    Spawn.bHideFromSceneOutliner = true;
    Spawn.OverrideLevel = World->GetCurrentLevel();
    ATargetPoint* Seed = World->SpawnActor<ATargetPoint>(Position, FRotator::ZeroRotator, Spawn);
    if (Seed)
    {
        Seed->SetActorLabel(FString::Printf(TEXT("View_%.0f_%.0f_%.0f"), Position.X, Position.Y, Position.Z), false);
    }
    return Seed;
}

int32 UInteriorFitLibrary::CountBrushTriangles(AVolume* Volume)
{
    if (!IsValid(Volume) || !Volume->Brush) return 0;
    int32 Count = 0;
    for (const FBspNode& Node : Volume->Brush->Nodes)
        Count += FMath::Max(0, static_cast<int32>(Node.NumVertices) - 2);
    return Count;
}

FString UInteriorFitLibrary::GetVolumeFaces(AVolume* Volume)
{
    TArray<TSharedPtr<FJsonValue>> Faces;
    if (!IsInGameThread() || !IsValid(Volume) || !Volume->Brush || !Volume->Brush->Polys) return TEXT("[]");
    const FTransform Transform = Volume->GetActorTransform();
    for (const FPoly& Poly : Volume->Brush->Polys->Element)
    {
        if (Poly.Vertices.Num() < 3) continue;
        const FVector First = Transform.TransformPosition(FVector(Poly.Vertices[0]));
        const FVector Second = Transform.TransformPosition(FVector(Poly.Vertices[1]));
        const FVector Third = Transform.TransformPosition(FVector(Poly.Vertices[2]));
        const FVector Normal = FVector::CrossProduct(Second - First, Third - First).GetSafeNormal();
        if (Normal.IsNearlyZero() || FMath::Abs(Normal.Z) > 0.15) continue;
        TSharedPtr<FJsonObject> Face = MakeShared<FJsonObject>();
        Face->SetArrayField(TEXT("normal"), VectorValues(Normal));
        TArray<TSharedPtr<FJsonValue>> Vertices;
        for (const FVector3f& Vertex : Poly.Vertices)
            Vertices.Add(MakeShared<FJsonValueArray>(VectorValues(Transform.TransformPosition(FVector(Vertex)))));
        Face->SetArrayField(TEXT("vertices"), Vertices);
        Faces.Add(MakeShared<FJsonValueObject>(Face));
    }
    FString JSON;
    FJsonSerializer::Serialize(Faces, TJsonWriterFactory<>::Create(&JSON));
    return JSON;
}

FString UInteriorFitLibrary::GetActorPanelFace(AActor* Actor)
{
    if (!IsInGameThread() || !IsValid(Actor)) return TEXT("[]");
    const FBox Box = Actor->CalculateComponentsBoundingBoxInLocalSpace(true);
    if (!Box.IsValid) return TEXT("[]");
    const FVector Center = Box.GetCenter();
    const FVector Extent = Box.GetExtent();
    const bool bAlongX = Extent.X < Extent.Y;
    const FVector Across = bAlongX ? FVector(0, Extent.Y + 60, 0) : FVector(Extent.X + 60, 0, 0);
    const FVector Up(0, 0, Extent.Z + 30);
    const FTransform Transform = Actor->GetActorTransform();
    const FVector Normal = Transform.TransformVectorNoScale(bAlongX ? FVector::ForwardVector : FVector::RightVector).GetSafeNormal();
    TSharedPtr<FJsonObject> Face = MakeShared<FJsonObject>();
    Face->SetArrayField(TEXT("normal"), VectorValues(Normal));
    TArray<TSharedPtr<FJsonValue>> Vertices;
    for (const FVector& Point : {Center - Across - Up, Center + Across - Up, Center + Across + Up, Center - Across + Up})
        Vertices.Add(MakeShared<FJsonValueArray>(VectorValues(Transform.TransformPosition(Point))));
    Face->SetArrayField(TEXT("vertices"), Vertices);
    FString JSON;
    FJsonSerializer::Serialize(TArray<TSharedPtr<FJsonValue>>{MakeShared<FJsonValueObject>(Face)}, TJsonWriterFactory<>::Create(&JSON));
    return JSON;
}

void UInteriorFitLibrary::FocusOpening(FVector Center, FVector HalfExtent)
{
    if (IsInGameThread() && GEditor && !Center.ContainsNaN() && !HalfExtent.ContainsNaN() && HalfExtent.GetMin() > 0.0)
        GEditor->MoveViewportCamerasToBox(FBox(Center - HalfExtent, Center + HalfExtent), true);
}

bool UInteriorFitLibrary::ShowOpenings(const FString& JSON)
{
    return IsInGameThread() && InteriorFitOpenings::Show(JSON);
}

bool UInteriorFitLibrary::DrawOpeningPreviews(UObject* WorldContext, const FString& JSON)
{
    if (!IsInGameThread() || !IsValid(WorldContext)) return false;
    UWorld* World = WorldContext->GetWorld();
    if (!IsValid(World) || World->WorldType != EWorldType::Editor || !IsValid(World->PersistentLineBatcher)) return false;
    constexpr uint32 OpeningBatchID = 0x49464F50;
    World->PersistentLineBatcher->ClearBatch(OpeningBatchID);
    TArray<TSharedPtr<FJsonValue>> Rows;
    if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Rows) || Rows.Num() > 128) return false;
    for (const TSharedPtr<FJsonValue>& Value : Rows)
    {
        const TSharedPtr<FJsonObject> Row = Value->AsObject();
        if (!Row.IsValid()) continue;
        const FVector Center = ReadVector(Row, TEXT("center"));
        const FVector Extent = ReadVector(Row, TEXT("half_extent"));
        double Yaw = 0.0;
        Row->TryGetNumberField(TEXT("yaw"), Yaw);
        if (Center.ContainsNaN() || Extent.ContainsNaN() || Extent.GetMin() <= 0.0 || !FMath::IsFinite(Yaw)) continue;
        bool bOpen = false;
        Row->TryGetBoolField(TEXT("open"), bOpen);
        const FLinearColor Color = bOpen ? FLinearColor::Green : FLinearColor(1.0f, 0.6f, 0.0f);
        World->PersistentLineBatcher->DrawBox(Center, Extent, FRotator(0.0, Yaw, 0.0).Quaternion(),
            Color, 300.0f, SDPG_Foreground, 2.0f, OpeningBatchID);
    }
    if (GEditor) GEditor->RedrawLevelEditingViewports();
    return true;
}

bool UInteriorFitLibrary::DrawPreview(UObject* WorldContext, FTransform Transform, FVector HalfExtent, FLinearColor Color)
{
    if (!IsInGameThread() || !IsValid(WorldContext)) return false;
    UWorld* World = WorldContext->GetWorld();
    if (!IsValid(World) || World->WorldType != EWorldType::Editor || !IsValid(World->PersistentLineBatcher)) return false;
    constexpr uint32 PreviewBatchID = 0x49464954;
    World->PersistentLineBatcher->ClearBatch(PreviewBatchID);
    if (Transform.ContainsNaN() || HalfExtent.ContainsNaN() || HalfExtent.GetMin() <= 0.0) return false;
    World->PersistentLineBatcher->DrawBox(Transform.GetLocation(), HalfExtent, Transform.GetRotation(),
        Color, 300.0f, SDPG_Foreground, 3.0f, PreviewBatchID);
    return true;
}

AVolume* UInteriorFitLibrary::CreateBoxVolume(UObject* WorldContext, TSubclassOf<AVolume> VolumeClass,
    FTransform Transform, FVector HalfExtent)
{
    if (!IsInGameThread() || !IsValid(WorldContext) || !VolumeClass ||
        VolumeClass->HasAnyClassFlags(CLASS_Abstract | CLASS_Deprecated) ||
        Transform.ContainsNaN() || HalfExtent.ContainsNaN() || HalfExtent.GetMin() <= 0.0) return nullptr;
    UWorld* World = WorldContext->GetWorld();
    if (!IsValid(World) || World->WorldType != EWorldType::Editor) return nullptr;
    FActorSpawnParameters Parameters;
    Parameters.ObjectFlags |= RF_Transactional;
    AVolume* Volume = World->SpawnActor<AVolume>(VolumeClass, Parameters);
    if (!Volume) return nullptr;
    Volume->Modify();
    UCubeBuilder* Builder = NewObject<UCubeBuilder>(Volume, NAME_None, RF_Transactional);
    Builder->X = HalfExtent.X * 2.0;
    Builder->Y = HalfExtent.Y * 2.0;
    Builder->Z = HalfExtent.Z * 2.0;
    UActorFactory::CreateBrushForVolumeActor(Volume, Builder);
    if (!Volume->Brush)
    {
        World->DestroyActor(Volume);
        return nullptr;
    }
    Volume->SetActorTransform(Transform);
    Volume->PostEditChange();
    Volume->UnregisterAllComponents(true);
    Volume->RegisterAllComponents();
    Volume->MarkPackageDirty();
    return Volume;
}

bool UInteriorFitLibrary::ContainsPoint(AVolume* Volume, FVector Position)
{
    return IsInGameThread() && IsValid(Volume) && !Position.ContainsNaN() && Volume->EncompassesPoint(Position);
}

void UInteriorFitLibrary::RefreshVolumeCollision(AVolume* Volume)
{
    if (!IsInGameThread() || !IsValid(Volume) || !Volume->GetWorld() ||
        Volume->GetWorld()->WorldType != EWorldType::Editor || !Volume->Brush) return;
    UBrushComponent* Brush = Volume->GetBrushComponent();
    FBSPOps::RebuildBrush(Volume->Brush);
    Brush->BuildSimpleBrushCollision();

}



