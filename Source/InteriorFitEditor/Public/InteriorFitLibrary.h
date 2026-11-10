#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "InteriorFitLibrary.generated.h"

class AVolume;
class UDynamicMesh;

/** Synchronous editor utilities. Created volumes are engine-native, without plugin runtime components. */
UCLASS()
class INTERIORFITEDITOR_API UInteriorFitLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Simple-collision solids: 0 separated/contact only, 1 interior overlap, -1 unsupported/bounded out.
     * Independent of merge eligibility; never alters either Room or its collision. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit")
    static int32 ClassifyRoomOverlap(AVolume* First, AVolume* Second);

    /** Bounded editor mesh audit: welded topology, duplicate/crossing/overlapping faces. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit")
    static FString AuditRoomMesh(UDynamicMesh* Mesh);

    /** Treat existing Room surfaces as virtual walls without changing their collision profile. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit")
    static TArray<FHitResult> ConstrainRoomRays(const TArray<AActor*>& Rooms,
        const TArray<FVector>& Starts, const TArray<FVector>& Ends, const TArray<FHitResult>& PhysicalHits);

    /** Snapshot the active perspective view in the editable world for an asynchronous fit. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit")
    static AActor* CreateViewportSeed();

    /** Editor-only outliner preview under Audio/Ambience; never plays audio. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit|Surface", meta=(WorldContext="WorldContext"))
    static AActor* CreateSurfacePreview(UObject* WorldContext, const FString& JSON);

    UFUNCTION(BlueprintCallable, Category="Interior Fit|Surface", meta=(WorldContext="WorldContext"))
    static bool ClearSurfacePreviews(UObject* WorldContext);

    /** Planar mesh boundary edges in world space; no grid quantization or actor creation. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit|Spline")
    static FString GetLakeSurfaceBoundary(const TArray<AActor*>& Sources);

    /** Samples selected source surfaces; returns a bounded heightfield JSON with no source references. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit|Area")
    static FString SampleAreaSurface(const TArray<AActor*>& Sources, float RequestedCellSize = 50.0f, bool ExcludeCoveredSurface = true);

    UFUNCTION(BlueprintCallable, Category="Interior Fit|Area", meta=(WorldContext="WorldContext"))
    static bool DrawAreaPreview(UObject* WorldContext, const FString& JSON);

    /** Dedicated preview batch, cleared by passing an empty array; never creates actors. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit|Spline", meta=(WorldContext="WorldContext"))
    static bool DrawSplinePreview(UObject* WorldContext, const TArray<FVector>& Points, bool Closed, bool OverBudget);

    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    static FString GetActorPanelFace(AActor* Actor);

    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    static void FocusOpening(FVector Center, FVector HalfExtent);

    /** Replace the first aligned box brush with the exact union and remove the second in one transaction. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit")
    static FString MergeTouchingBoxes(AVolume* First, AVolume* Second);

    /** Rebuild physics from the finished editor brush before sampling fitted native Rooms. */
    UFUNCTION(BlueprintCallable, Category="Interior Fit")
    static void RefreshVolumeCollision(AVolume* Volume);

    /** Triangle count after Unreal splits polygons into BSP nodes. */
    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    static int32 CountBrushTriangles(AVolume* Volume);

    /** Actual world-space vertical brush polygons, independent of decorative actor bounds. */
    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    static FString GetVolumeFaces(AVolume* Volume);

    /** Value-only candidate panel. JSON never holds UObject references. */
    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    static bool ShowOpenings(const FString& JSON);

    UFUNCTION(BlueprintCallable, Category = "Interior Fit", meta = (WorldContext = "WorldContext"))
    static bool DrawOpeningPreviews(UObject* WorldContext, const FString& JSON);

    UFUNCTION(BlueprintCallable, Category = "Interior Fit", meta = (WorldContext = "WorldContext"))
    static bool DrawPreview(UObject* WorldContext, FTransform Transform, FVector HalfExtent, FLinearColor Color);

    UFUNCTION(BlueprintCallable, Category = "Interior Fit", meta = (WorldContext = "WorldContext"))
    static AVolume* CreateBoxVolume(UObject* WorldContext, TSubclassOf<AVolume> VolumeClass,
        FTransform Transform, FVector HalfExtent);

    UFUNCTION(BlueprintPure, Category = "Interior Fit")
    static bool ContainsPoint(AVolume* Volume, FVector Position);
};


