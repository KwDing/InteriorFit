#include "InteriorFitArea.h"
#include "Components/SceneComponent.h"
AInteriorFitArea::AInteriorFitArea()
{
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("AreaRoot"));
    PrimaryActorTick.bCanEverTick = false;
}
bool AInteriorFitArea::IsShapeValid() const
{
    UpdateIndex();
    return bShapeValid;
}

void AInteriorFitArea::SetSurfaceCells(const TArray<FVector>& InCells)
{
    SurfaceCells = InCells;
    bIndexReady = false;
}

void AInteriorFitArea::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    bIndexReady = false;
}

#if WITH_EDITOR
void AInteriorFitArea::PostEditChangeProperty(FPropertyChangedEvent& Event)
{
    bIndexReady = false;
    Super::PostEditChangeProperty(Event);
}

void AInteriorFitArea::PostEditUndo()
{
    bIndexReady = false;
    Super::PostEditUndo();
}
#endif

void AInteriorFitArea::UpdateIndex() const
{
    if (bIndexReady && CachedCellSize == CellSize && CachedAbove == HeightAboveSurface && CachedBelow == DepthBelowSurface) return;
    bIndexReady = true;
    CachedCellSize = CellSize;
    CachedAbove = HeightAboveSurface;
    CachedBelow = DepthBelowSurface;
    bShapeValid = false;
    if (SurfaceCells.IsEmpty() || SurfaceCells.Num() > 8192 || !FMath::IsFinite(CellSize) || CellSize <= 0 ||
        !FMath::IsFinite(HeightAboveSurface) || HeightAboveSurface < 0 ||
        !FMath::IsFinite(DepthBelowSurface) || DepthBelowSurface < 0) return;
    TArray<FBox> Boxes;
    Boxes.Reserve(SurfaceCells.Num());
    const FVector Lower(CellSize * .5, CellSize * .5, DepthBelowSurface);
    const FVector Upper(CellSize * .5, CellSize * .5, HeightAboveSurface);
    for (const FVector& Cell : SurfaceCells)
    {
        if (Cell.ContainsNaN()) return;
        Boxes.Emplace(Cell - Lower, Cell + Upper);
    }
    SpatialIndex.Build(Boxes);
    bShapeValid = true;
}

float AInteriorFitArea::GetBoundsDistanceM(const FVector& Listener) const
{
    if (!IsShapeValid()) return TNumericLimits<float>::Max();
    return FMath::Sqrt(SpatialIndex.GetBounds().TransformBy(GetActorTransform()).ComputeSquaredDistanceToPoint(Listener)) / 100;
}
bool AInteriorFitArea::FindClosestPoint(FVector ListenerPosition, FVector& ClosestPoint, float& Distance) const
{
    int32 CellIndex = INDEX_NONE;
    return FindClosestCell(ListenerPosition, ClosestPoint, Distance, CellIndex);
}

bool AInteriorFitArea::GetClosestSurfaceCell(const FVector& Position, FVector& OutLocalCentre) const
{
    OutLocalCentre = FVector::ZeroVector;
    FVector Point;
    float Distance = 0;
    int32 CellIndex = INDEX_NONE;
    if (!FindClosestCell(Position, Point, Distance, CellIndex)) return false;
    OutLocalCentre = SurfaceCells[CellIndex];
    return true;
}

bool AInteriorFitArea::FindClosestCell(const FVector& ListenerPosition, FVector& ClosestPoint, float& Distance, int32& OutCellIndex) const
{
    OutCellIndex = INDEX_NONE;
    ClosestPoint = ListenerPosition;
    Distance = 0;
    if (!IsShapeValid() || ListenerPosition.ContainsNaN()) return false;
    const FTransform Transform = GetActorTransform();
    if (Transform.ContainsNaN() || Transform.GetScale3D().GetAbsMin() < UE_SMALL_NUMBER) return false;
    const FVector Local = Transform.InverseTransformPosition(ListenerPosition);
    double Best = TNumericLimits<double>::Max();
    const double Half = CellSize * 0.5;
    int32 BestID = MAX_int32;
    SpatialIndex.FindNearest(Local, Transform.GetScale3D().GetAbs(), Best, [&](int32 ID, double& CurrentBest)
    {
        const FVector& Cell = SurfaceCells[ID];
        const FVector Point(FMath::Clamp(Local.X, Cell.X - Half, Cell.X + Half),
            FMath::Clamp(Local.Y, Cell.Y - Half, Cell.Y + Half),
            FMath::Clamp(Local.Z, Cell.Z - DepthBelowSurface, Cell.Z + HeightAboveSurface));
        const FVector WorldPoint = Transform.TransformPosition(Point);
        const double Squared = FVector::DistSquared(WorldPoint, ListenerPosition);
        if (Squared < CurrentBest || (Squared == CurrentBest && ID < BestID))
        { CurrentBest = Squared; BestID = ID; ClosestPoint = WorldPoint; }
    });
    if (BestID == MAX_int32) return false;
    Distance = FMath::Sqrt(Best);
    OutCellIndex = BestID;
    return true;
}
