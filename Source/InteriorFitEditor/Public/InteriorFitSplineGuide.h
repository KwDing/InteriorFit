#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "InteriorFitSplineGuide.generated.h"

class USplineComponent;

/** Editable geometry-only result. Excluded from gameplay, with no audio or water dependencies. */
UCLASS()
class INTERIORFITEDITOR_API AInteriorFitSplineGuide : public AActor
{
    GENERATED_BODY()
public:
    AInteriorFitSplineGuide();
    virtual bool IsEditorOnly() const override { return true; }
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Fit")
    TObjectPtr<USplineComponent> Spline;
};
