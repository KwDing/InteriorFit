#include "InteriorFitViewportTools.h"

#include "Editor.h"
#include "Engine/TargetPoint.h"
#include "Engine/World.h"
#include "LevelEditorViewport.h"

AActor* InteriorFitViewportTools::CreateViewportSeed()
{
    if (!GEditor || GEditor->PlayWorld || !GCurrentLevelEditingViewportClient)
    {
        return nullptr;
    }
    FLevelEditorViewportClient* View = GCurrentLevelEditingViewportClient;
    UWorld* World = GEditor->GetEditorWorldContext().World();
    if (!World || View->GetWorld() != World || !View->IsPerspective())
    {
        return nullptr;
    }

    const FVector Position = View->GetViewLocation();
    FActorSpawnParameters Spawn;
    Spawn.ObjectFlags = RF_Transient;
    Spawn.bCreateActorPackage = false;
    Spawn.bHideFromSceneOutliner = true;
    Spawn.OverrideLevel = World->GetCurrentLevel();
    ATargetPoint* Seed = World->SpawnActor<ATargetPoint>(Position, FRotator::ZeroRotator, Spawn);
    if (Seed)
    {
        Seed->SetActorLabel(
            FString::Printf(TEXT("View_%.0f_%.0f_%.0f"), Position.X, Position.Y, Position.Z),
            false);
    }
    return Seed;
}

void InteriorFitViewportTools::FocusOpening(FVector Center, FVector HalfExtent)
{
    if (IsInGameThread() && GEditor && !Center.ContainsNaN() && !HalfExtent.ContainsNaN() &&
        HalfExtent.GetMin() > 0.0)
    {
        GEditor->MoveViewportCamerasToBox(FBox(Center - HalfExtent, Center + HalfExtent), true);
    }
}
