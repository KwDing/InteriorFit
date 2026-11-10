#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "InteriorFitSpatialIndex.h"
#include "InteriorFitArea.generated.h"

/** Baked surface columns. No source mesh or editor dependency at runtime. */
UCLASS(BlueprintType)
class INTERIORFITRUNTIME_API AInteriorFitArea : public AActor
{
    GENERATED_BODY()
public:
    AInteriorFitArea();
    /** Runtime cell edits must use this setter so the index cannot become stale. */
    UFUNCTION(BlueprintSetter)
    void SetSurfaceCells(const TArray<FVector>& InCells);
    const TArray<FVector>& GetSurfaceCells() const { return SurfaceCells; }
    /** Blueprint reads return a copy: in-place array nodes cannot bypass cache invalidation. */
    UFUNCTION(BlueprintGetter)
    TArray<FVector> GetSurfaceCellsForBlueprint() const { return SurfaceCells; }
    float GetBoundsDistanceM(const FVector& Listener) const;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Area Shape", meta=(ClampMin="1", Units="cm"))
    float CellSize = 100.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Area Shape", meta=(ClampMin="0", Units="cm"))
    float HeightAboveSurface = 200.0f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Area Shape", meta=(ClampMin="0", Units="cm"))
    float DepthBelowSurface = 500.0f;
    UFUNCTION(BlueprintPure, Category="Area Shape")
    bool IsShapeValid() const;
    UFUNCTION(BlueprintPure, Category="Area Shape")
    bool FindClosestPoint(FVector ListenerPosition, FVector& ClosestPoint, float& Distance) const;
    /** Debug/authoring lookup using the same index, returns the authored cell centre in local space. */
    bool GetClosestSurfaceCell(const FVector& Position, FVector& OutLocalCentre) const;

protected:
    virtual void OnConstruction(const FTransform& Transform) override;
#if WITH_EDITOR
    virtual void PostEditChangeProperty(FPropertyChangedEvent& Event) override;
    virtual void PostEditUndo() override;
#endif

private:
    void UpdateIndex() const;
    bool FindClosestCell(const FVector& Position, FVector& OutPoint, float& OutDistance, int32& OutCellIndex) const;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, BlueprintGetter=GetSurfaceCellsForBlueprint, BlueprintSetter=SetSurfaceCells, Category="Area Shape", meta=(AllowPrivateAccess="true"))
    TArray<FVector> SurfaceCells;
    mutable FInteriorFitSpatialIndex SpatialIndex;
    mutable bool bIndexReady = false;
    mutable bool bShapeValid = false;
    mutable float CachedCellSize = 0;
    mutable float CachedAbove = 0;
    mutable float CachedBelow = 0;
};
