#include "InteriorFitVolumeAuthoring.h"

#include "InteriorFitEditorWorld.h"

#include "ActorFactories/ActorFactory.h"
#include "BSPOps.h"
#include "Builders/CubeBuilder.h"
#include "Components/BrushComponent.h"
#include "Engine/World.h"
#include "GameFramework/Volume.h"
#include "Model.h"

AVolume* InteriorFitVolumeAuthoring::CreateBoxVolume(UObject* WorldContext,
                                                     TSubclassOf<AVolume> VolumeClass,
                                                     FTransform Transform, FVector HalfExtent)
{
    if (!IsInGameThread() || !IsValid(WorldContext) || !VolumeClass ||
        VolumeClass->HasAnyClassFlags(CLASS_Abstract | CLASS_Deprecated) ||
        Transform.ContainsNaN() || HalfExtent.ContainsNaN() || HalfExtent.GetMin() <= 0.0)
    {
        return nullptr;
    }
    UWorld* World = WorldContext->GetWorld();
    if (!InteriorFitEditorWorld::IsEditorWorld(World))
    {
        return nullptr;
    }
    FActorSpawnParameters Parameters;
    Parameters.ObjectFlags |= RF_Transactional;
    AVolume* Volume = World->SpawnActor<AVolume>(VolumeClass, Parameters);
    if (!Volume)
    {
        return nullptr;
    }
    Volume->Modify();
    UCubeBuilder* Builder = NewObject<UCubeBuilder>(Volume, NAME_None, RF_Transactional);
    Builder->X = HalfExtent.X * 2.0;
    Builder->Y = HalfExtent.Y * 2.0;
    Builder->Z = HalfExtent.Z * 2.0;
    UActorFactory::CreateBrushForVolumeActor(Volume, Builder);
    if (!Volume->Brush || !IsValid(Volume->GetBrushComponent()))
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

void InteriorFitVolumeAuthoring::RefreshVolumeCollision(AVolume* Volume)
{
    if (!IsInGameThread() || !IsValid(Volume) ||
        !InteriorFitEditorWorld::IsEditorWorld(Volume->GetWorld()) || !Volume->Brush)
    {
        return;
    }
    UBrushComponent* Brush = Volume->GetBrushComponent();
    if (!IsValid(Brush))
    {
        return;
    }
    FBSPOps::RebuildBrush(Volume->Brush);
    Brush->BuildSimpleBrushCollision();
}
