#pragma once

#include "Components/LineBatchComponent.h"
#include "Engine/World.h"

namespace InteriorFitEditorWorld
{
    inline bool IsEditorWorld(const UWorld* World)
    {
        return IsValid(World) && World->WorldType == EWorldType::Editor;
    }

    inline ULineBatchComponent* GetPreviewLineBatcher(UObject* Context)
    {
        if (!IsInGameThread() || !IsValid(Context))
        {
            return nullptr;
        }
        const UWorld* World = Context->GetWorld();
        if (!IsEditorWorld(World))
        {
            return nullptr;
        }
        return IsValid(World->PersistentLineBatcher) ? World->PersistentLineBatcher.Get() : nullptr;
    }
} // namespace InteriorFitEditorWorld
