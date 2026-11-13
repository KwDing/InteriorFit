#include "InteriorFitPreviewActors.h"

#include "InteriorFitEditorWorld.h"

#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "InteriorFitSurfacePreview.h"

AActor* InteriorFitPreviewActors::CreateSurfacePreview(UObject* WorldContext, const FString& JSON)
{
    if (!IsInGameThread() || !IsValid(WorldContext) || !GEditor || GEditor->PlayWorld)
    {
        return nullptr;
    }
    UWorld* World = WorldContext->GetWorld();
    if (!InteriorFitEditorWorld::IsEditorWorld(World))
    {
        return nullptr;
    }
    FActorSpawnParameters Parameters;
    Parameters.ObjectFlags = RF_DuplicateTransient | RF_Transactional;
    AInteriorFitSurfacePreview* Preview = World->SpawnActor<AInteriorFitSurfacePreview>(Parameters);
    if (!Preview)
    {
        return nullptr;
    }
    if (!Preview->InitializePreview(JSON))
    {
        World->DestroyActor(Preview);
        return nullptr;
    }
    GEditor->RedrawLevelEditingViewports();
    return Preview;
}

bool InteriorFitPreviewActors::ClearSurfacePreviews(UObject* WorldContext)
{
    if (!IsInGameThread() || !IsValid(WorldContext) || !GEditor || GEditor->PlayWorld)
    {
        return false;
    }
    UWorld* World = WorldContext->GetWorld();
    if (!InteriorFitEditorWorld::IsEditorWorld(World))
    {
        return false;
    }
    TArray<AActor*> Previews;
    for (TActorIterator<AInteriorFitSurfacePreview> It(World); It; ++It)
    {
        Previews.Add(*It);
    }
    bool bCleared = true;
    for (AActor* Preview : Previews)
    {
        GEditor->SelectActor(Preview, false, false);
        if (!World->DestroyActor(Preview))
        {
            bCleared = false;
        }
    }
    if (!Previews.IsEmpty())
    {
        GEditor->NoteSelectionChange();
    }
    GEditor->RedrawLevelEditingViewports();
    return bCleared;
}
