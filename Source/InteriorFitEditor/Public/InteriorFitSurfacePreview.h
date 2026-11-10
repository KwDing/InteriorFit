#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "InteriorFitSurfacePreview.generated.h"

class ULineBatchComponent;

/** Editor-only authoring geometry. Owns no sound, source meshes or deferred callbacks. */
UCLASS(NotBlueprintable)
class INTERIORFITEDITOR_API AInteriorFitSurfacePreview : public AActor
{
    GENERATED_BODY()
public:
    AInteriorFitSurfacePreview();
    bool InitializePreview(const FString& JSON);
    virtual void PostLoad() override;

    UPROPERTY(BlueprintReadOnly, Category="Audio Preview")
    FString PreviewJSON;
private:
    UPROPERTY()
    TObjectPtr<ULineBatchComponent> Lines;
};
