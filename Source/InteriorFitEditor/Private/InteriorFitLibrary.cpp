#include "InteriorFitLibrary.h"

#include "Engine/HitResult.h"
#include "GameFramework/Volume.h"

#include "Geometry/InteriorFitBrushQueries.h"
#include "Geometry/InteriorFitRoomMeshAudit.h"
#include "Geometry/InteriorFitRoomOverlap.h"
#include "Geometry/InteriorFitRoomRayConstraints.h"
#include "InteriorFitOpeningsPanel.h"
#include "InteriorFitViewportTools.h"
#include "Portals/InteriorFitOpeningFaces.h"
#include "Portals/InteriorFitOpeningPreview.h"
#include "Rooms/InteriorFitRoomBoxMerger.h"
#include "Rooms/InteriorFitRoomBoxPreview.h"
#include "Rooms/InteriorFitVolumeAuthoring.h"
#include "Surfaces/InteriorFitAreaSurfaceSampler.h"
#include "Surfaces/InteriorFitPreviewActors.h"
#include "Surfaces/InteriorFitSplineBoundaryExtractor.h"
#include "Surfaces/InteriorFitSurfaceLinePreview.h"

int32 UInteriorFitLibrary::ClassifyRoomOverlap(AVolume* First, AVolume* Second)
{
    return InteriorFitRoomOverlap::ClassifyRoomOverlap(First, Second);
}

FString UInteriorFitLibrary::AuditRoomMesh(UDynamicMesh* Mesh)
{
    return InteriorFitRoomMeshAudit::AuditRoomMesh(Mesh);
}

TArray<FHitResult> UInteriorFitLibrary::ConstrainRoomRays(const TArray<AActor*>& Rooms,
                                                          const TArray<FVector>& Starts,
                                                          const TArray<FVector>& Ends,
                                                          const TArray<FHitResult>& PhysicalHits)
{
    return InteriorFitRoomRayConstraints::ConstrainRoomRays(Rooms, Starts, Ends, PhysicalHits);
}

AActor* UInteriorFitLibrary::CreateViewportSeed()
{
    return InteriorFitViewportTools::CreateViewportSeed();
}

AActor* UInteriorFitLibrary::CreateSurfacePreview(UObject* WorldContext, const FString& JSON)
{
    return InteriorFitPreviewActors::CreateSurfacePreview(WorldContext, JSON);
}

bool UInteriorFitLibrary::ClearSurfacePreviews(UObject* WorldContext)
{
    return InteriorFitPreviewActors::ClearSurfacePreviews(WorldContext);
}

FString UInteriorFitLibrary::GetLakeSurfaceBoundary(const TArray<AActor*>& Sources)
{
    return InteriorFitSplineBoundaryExtractor::ExtractPlanarBoundary(Sources);
}

FString UInteriorFitLibrary::SampleAreaSurface(const TArray<AActor*>& Sources,
                                               float RequestedCellSize, bool ExcludeCoveredSurface)
{
    return InteriorFitAreaSurfaceSampler::SampleAreaSurface(Sources, RequestedCellSize,
                                                            ExcludeCoveredSurface);
}

bool UInteriorFitLibrary::DrawAreaPreview(UObject* WorldContext, const FString& JSON)
{
    return InteriorFitSurfaceLinePreview::DrawAreaPreview(WorldContext, JSON);
}

bool UInteriorFitLibrary::DrawSplinePreview(UObject* WorldContext, const TArray<FVector>& Points,
                                            bool Closed, bool OverBudget)
{
    return InteriorFitSurfaceLinePreview::DrawSplinePreview(WorldContext, Points, Closed,
                                                            OverBudget);
}

FString UInteriorFitLibrary::GetActorPanelFace(AActor* Actor)
{
    return InteriorFitOpeningFaces::GetActorPanelFace(Actor);
}

void UInteriorFitLibrary::FocusOpening(FVector Center, FVector HalfExtent)
{
    InteriorFitViewportTools::FocusOpening(Center, HalfExtent);
}

FString UInteriorFitLibrary::MergeTouchingBoxes(AVolume* First, AVolume* Second)
{
    return InteriorFitRoomBoxMerger::MergeTouchingBoxes(First, Second);
}

void UInteriorFitLibrary::RefreshVolumeCollision(AVolume* Volume)
{
    InteriorFitVolumeAuthoring::RefreshVolumeCollision(Volume);
}

int32 UInteriorFitLibrary::CountBrushTriangles(AVolume* Volume)
{
    return InteriorFitBrushQueries::CountBrushTriangles(Volume);
}

FString UInteriorFitLibrary::GetVolumeFaces(AVolume* Volume)
{
    return InteriorFitOpeningFaces::GetVolumeFaces(Volume);
}

bool UInteriorFitLibrary::ShowOpenings(const FString& JSON)
{
    return IsInGameThread() && InteriorFitOpenings::Show(JSON);
}

bool UInteriorFitLibrary::DrawOpeningPreviews(UObject* WorldContext, const FString& JSON)
{
    return InteriorFitOpeningPreview::DrawOpeningPreviews(WorldContext, JSON);
}

bool UInteriorFitLibrary::DrawPreview(UObject* WorldContext, FTransform Transform,
                                      FVector HalfExtent, FLinearColor Color)
{
    return InteriorFitRoomBoxPreview::DrawPreview(WorldContext, Transform, HalfExtent, Color);
}

AVolume* UInteriorFitLibrary::CreateBoxVolume(UObject* WorldContext,
                                              TSubclassOf<AVolume> VolumeClass,
                                              FTransform Transform, FVector HalfExtent)
{
    return InteriorFitVolumeAuthoring::CreateBoxVolume(WorldContext, VolumeClass, Transform,
                                                       HalfExtent);
}

bool UInteriorFitLibrary::ContainsPoint(AVolume* Volume, FVector Position)
{
    return InteriorFitBrushQueries::ContainsPoint(Volume, Position);
}

FString UInteriorFitLibrary::SampleAreaSurfaceWithCoverage(const TArray<AActor*>& Sources,
                                                           float RequestedCellSize,
                                                           EInteriorFitSurfaceCoverage Coverage)
{
    return SampleAreaSurface(Sources, RequestedCellSize,
                             Coverage == EInteriorFitSurfaceCoverage::ExposedOnly);
}

bool UInteriorFitLibrary::DrawSplinePreviewWithStyle(UObject* WorldContext,
                                                     const TArray<FVector>& Points,
                                                     EInteriorFitSplineClosure Closure,
                                                     EInteriorFitSplineBudgetStatus BudgetStatus)
{
    return DrawSplinePreview(WorldContext, Points, Closure == EInteriorFitSplineClosure::Closed,
                             BudgetStatus == EInteriorFitSplineBudgetStatus::OverBudget);
}
