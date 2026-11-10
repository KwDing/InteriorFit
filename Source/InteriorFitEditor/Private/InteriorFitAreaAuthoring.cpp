#include "InteriorFitLibrary.h"
#include "Components/StaticMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/LineBatchComponent.h"
#include "Engine/StaticMesh.h"
#include "StaticMeshResources.h"
#include "Engine/World.h"
#include "Editor.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SceneManagement.h"

namespace
{
struct FAreaGrid
{
    FVector Origin;
    double Step;
    int32 Width;
    int32 Height;
    TArray<double> Heights;
    int64 Work = 0;
    int64 Triangles = 0;
    bool Rasterize(const FVector &A, const FVector &B, const FVector &C)
    {
        const double Denom = (B.Y - C.Y) * (A.X - C.X) + (C.X - B.X) * (A.Y - C.Y);
        if (FMath::Abs(Denom) < 0.01)
            return true;
        const int32 Left =
            FMath::Clamp(FMath::FloorToInt((FMath::Min3(A.X, B.X, C.X) - Origin.X) / Step), 0, Width - 1);
        const int32 Right =
            FMath::Clamp(FMath::FloorToInt((FMath::Max3(A.X, B.X, C.X) - Origin.X) / Step), 0, Width - 1);
        const int32 Bottom =
            FMath::Clamp(FMath::FloorToInt((FMath::Min3(A.Y, B.Y, C.Y) - Origin.Y) / Step), 0, Height - 1);
        const int32 Top =
            FMath::Clamp(FMath::FloorToInt((FMath::Max3(A.Y, B.Y, C.Y) - Origin.Y) / Step), 0, Height - 1);
        Work += static_cast<int64>(Right - Left + 1) * (Top - Bottom + 1);
        if (Work > 8000000)
            return false;
        for (int32 Y = Bottom; Y <= Top; ++Y)
            for (int32 X = Left; X <= Right; ++X)
            {
                const double PX = Origin.X + (X + 0.5) * Step, PY = Origin.Y + (Y + 0.5) * Step;
                const double U = ((B.Y - C.Y) * (PX - C.X) + (C.X - B.X) * (PY - C.Y)) / Denom;
                const double V = ((C.Y - A.Y) * (PX - C.X) + (A.X - C.X) * (PY - C.Y)) / Denom;
                if (U < -0.00001 || V < -0.00001 || U + V > 1.00001)
                    continue;
                Heights[Y * Width + X] = FMath::Max(Heights[Y * Width + X], U * A.Z + V * B.Z + (1 - U - V) * C.Z);
            }
        return true;
    }
};
FString Encode(const TSharedRef<FJsonObject> &Data)
{
    FString JSON;
    FJsonSerializer::Serialize(Data, TJsonWriterFactory<>::Create(&JSON));
    return JSON;
}
FString Fail(const TCHAR *Message)
{
    TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
    Data->SetStringField(TEXT("error"), Message);
    return Encode(Data);
}
TArray<TSharedPtr<FJsonValue>> VectorJSON(const FVector &V)
{
    return {MakeShared<FJsonValueNumber>(V.X), MakeShared<FJsonValueNumber>(V.Y), MakeShared<FJsonValueNumber>(V.Z)};
}
bool RasterMesh(UStaticMeshComponent *Component, FAreaGrid &Grid)
{
    UStaticMesh *Mesh = Component->GetStaticMesh();
    if (!Mesh || !Mesh->GetRenderData() || Mesh->GetRenderData()->LODResources.IsEmpty())
        return false;
    const FStaticMeshLODResources &LOD = Mesh->GetRenderData()->LODResources[0];
    const FIndexArrayView Indices = LOD.IndexBuffer.GetArrayView();
    if (Indices.Num() > 1500000)
        return false;
    UInstancedStaticMeshComponent *Instances = Cast<UInstancedStaticMeshComponent>(Component);
    const int32 Count = Instances ? Instances->GetInstanceCount() : 1;
    if (Count > 1024)
        return false;
    for (int32 Instance = 0; Instance < Count; ++Instance)
    {
        FTransform Transform = Component->GetComponentTransform();
        if (Instances && !Instances->GetInstanceTransform(Instance, Transform, true))
            return false;
        for (int32 Index = 0; Index + 2 < Indices.Num(); Index += 3)
        {
            if (++Grid.Triangles > 500000)
                return false;
            FVector Points[3];
            for (int32 Corner = 0; Corner < 3; ++Corner)
                Points[Corner] = Transform.TransformPosition(
                    FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(Indices[Index + Corner])));
            if (!Grid.Rasterize(Points[0], Points[1], Points[2]))
                return false;
        }
    }
    return true;
}
} // namespace

namespace
{
// Weld render-vertex seams at 0.01 cm; retain the original, unquantized position.
struct FLakeBoundary
{
    TMap<FIntVector, int32> VertexIDs;
    TArray<FVector> Positions;
    TMap<FIntPoint, int32> EdgeUses;
    int32 TriangleCount = 0;

    int32 AddVertex(const FVector &Position)
    {
        const FIntVector Key(FMath::RoundToInt(Position.X * 100), FMath::RoundToInt(Position.Y * 100),
                             FMath::RoundToInt(Position.Z * 100));
        if (const int32 *Existing = VertexIDs.Find(Key))
            return *Existing;
        const int32 ID = Positions.Add(Position);
        VertexIDs.Add(Key, ID);
        return ID;
    }

    bool AddMesh(UStaticMeshComponent *Component)
    {
        const UStaticMesh *Mesh = Component->GetStaticMesh();
        if (!Mesh || !Mesh->GetRenderData() || Mesh->GetRenderData()->LODResources.IsEmpty())
            return false;
        const FStaticMeshLODResources &LOD = Mesh->GetRenderData()->LODResources[0];
        const FIndexArrayView Indices = LOD.IndexBuffer.GetArrayView();
        UInstancedStaticMeshComponent *Instances = Cast<UInstancedStaticMeshComponent>(Component);
        const int32 Count = Instances ? Instances->GetInstanceCount() : 1;
        if (Count > 1024 || static_cast<int64>(Indices.Num()) * Count > 1500000)
            return false;
        for (int32 Instance = 0; Instance < Count; ++Instance)
        {
            FTransform Transform = Component->GetComponentTransform();
            if (Instances && !Instances->GetInstanceTransform(Instance, Transform, true))
                return false;
            for (int32 Index = 0; Index + 2 < Indices.Num(); Index += 3)
            {
                if (++TriangleCount > 500000)
                    return false;
                int32 IDs[3];
                for (int32 Corner = 0; Corner < 3; ++Corner)
                {
                    const FVector Position = Transform.TransformPosition(
                        FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(Indices[Index + Corner])));
                    if (Position.ContainsNaN() || Position.GetAbsMax() > 10000000)
                        return false;
                    if (!Positions.IsEmpty() && FMath::Abs(Position.Z - Positions[0].Z) > 1)
                        return false;
                    IDs[Corner] = AddVertex(Position);
                }
                if (IDs[0] == IDs[1] || IDs[1] == IDs[2] || IDs[2] == IDs[0])
                    continue;
                for (int32 Corner = 0; Corner < 3; ++Corner)
                {
                    const int32 A = IDs[Corner];
                    const int32 B = IDs[(Corner + 1) % 3];
                    if (++EdgeUses.FindOrAdd(FIntPoint(FMath::Min(A, B), FMath::Max(A, B))) > 2)
                        return false;
                }
            }
        }
        return true;
    }
};
} // namespace

FString UInteriorFitLibrary::GetLakeSurfaceBoundary(const TArray<AActor *> &Sources)
{
    if (!IsInGameThread() || Sources.IsEmpty() || Sources.Num() > 128)
        return Fail(TEXT("Select planar water mesh actors."));
    UWorld *World = IsValid(Sources[0]) ? Sources[0]->GetWorld() : nullptr;
    if (!World || World->WorldType != EWorldType::Editor)
        return Fail(TEXT("An editor world is required."));
    FLakeBoundary Boundary;
    for (AActor *Actor : Sources)
    {
        if (!IsValid(Actor) || Actor->GetWorld() != World)
            return Fail(TEXT("Invalid water source."));
        TInlineComponentArray<UStaticMeshComponent *> Components;
        Actor->GetComponents(Components);
        if (Components.IsEmpty())
            return Fail(TEXT("Exact lake outline requires a planar static mesh or an existing spline."));
        for (UStaticMeshComponent *Component : Components)
        {
            if (!IsValid(Component) || !Component->IsRegistered() || Component->IsEditorOnly())
                continue;
            if (!Boundary.AddMesh(Component))
                return Fail(TEXT("Lake mesh must be horizontal, manifold and within the geometry budget. Select only "
                                 "the water sheet, or use an existing closed spline."));
        }
    }
    TArray<TSharedPtr<FJsonValue>> Edges;
    for (const auto &Entry : Boundary.EdgeUses)
    {
        if (Entry.Value != 1)
            continue;
        TArray<TSharedPtr<FJsonValue>> Pair;
        Pair.Add(MakeShared<FJsonValueArray>(VectorJSON(Boundary.Positions[Entry.Key.X])));
        Pair.Add(MakeShared<FJsonValueArray>(VectorJSON(Boundary.Positions[Entry.Key.Y])));
        Edges.Add(MakeShared<FJsonValueArray>(Pair));
    }
    if (Edges.IsEmpty() || Edges.Num() > 8192)
        return Fail(TEXT("Lake boundary must contain 3-8192 edges. Use a simpler source mesh or an existing spline."));
    TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
    Data->SetArrayField(TEXT("edges"), Edges);
    Data->SetNumberField(TEXT("triangles"), Boundary.TriangleCount);
    return Encode(Data);
}

namespace
{
FString EncodeExposedCells(UWorld *World, const FBox &Bounds, const FCollisionQueryParams &Query, const FAreaGrid &Grid,
                           bool ExcludeCoveredSurface)
{
    TArray<TSharedPtr<FJsonValue>> Cells;
    for (int32 Y = 0; Y < Grid.Height; ++Y)
        for (int32 X = 0; X < Grid.Width; ++X)
        {
            const double Z = Grid.Heights[Y * Grid.Width + X];
            if (Z == -TNumericLimits<double>::Max())
                continue;
            const FVector Point(Grid.Origin.X + (X + 0.5) * Grid.Step, Grid.Origin.Y + (Y + 0.5) * Grid.Step, Z);
            FHitResult Cover;
            if (ExcludeCoveredSurface &&
                World->LineTraceSingleByChannel(Cover, FVector(Point.X, Point.Y, Bounds.Max.Z + 10000),
                                                Point + FVector(0, 0, 5), ECC_Visibility, Query))
                continue;
            Cells.Add(MakeShared<FJsonValueArray>(VectorJSON(Point - Grid.Origin)));
        }
    if (Cells.IsEmpty())
        return Fail(
            TEXT("No exposed surface cells. Check geometry/collision or disable exclude_covered in area settings."));
    TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
    Data->SetArrayField(TEXT("origin"), VectorJSON(Grid.Origin));
    Data->SetArrayField(TEXT("cells"), Cells);
    Data->SetNumberField(TEXT("cell_size"), Grid.Step);
    Data->SetNumberField(TEXT("sample_work"), Grid.Work);
    return Encode(Data);
}

// Prefer source triangles. Components without a static mesh use bounded vertical traces.
FString SampleComponents(const TArray<UPrimitiveComponent *> &Components, const FBox &Bounds,
                         const FCollisionQueryParams &Query, FAreaGrid &Grid)
{
    for (UPrimitiveComponent *Component : Components)
    {
        if (UStaticMeshComponent *Mesh = Cast<UStaticMeshComponent>(Component))
        {
            if (!RasterMesh(Mesh, Grid))
                return Fail(TEXT(
                    "Mesh render geometry unavailable or sample budget exceeded. Use fewer actors or a coarser grid."));
            continue;
        }
        for (int32 Y = 0; Y < Grid.Height; ++Y)
            for (int32 X = 0; X < Grid.Width; ++X)
            {
                if (++Grid.Work > 8000000)
                    return Fail(TEXT("Surface trace budget exceeded."));
                const FVector Start(Grid.Origin.X + (X + 0.5) * Grid.Step, Grid.Origin.Y + (Y + 0.5) * Grid.Step,
                                    Bounds.Max.Z + 100);
                FHitResult Hit;
                if (Component->LineTraceComponent(Hit, Start, FVector(Start.X, Start.Y, Bounds.Min.Z - 100), Query))
                    Grid.Heights[Y * Grid.Width + X] = FMath::Max(Grid.Heights[Y * Grid.Width + X], Hit.ImpactPoint.Z);
            }
    }
    return {};
}
} // namespace

FString UInteriorFitLibrary::SampleAreaSurface(const TArray<AActor *> &Sources, float RequestedCellSize,
                                               bool ExcludeCoveredSurface)
{
    if (!IsInGameThread() || Sources.IsEmpty() || Sources.Num() > 128 || !FMath::IsFinite(RequestedCellSize) ||
        RequestedCellSize < 25)
        return Fail(TEXT("Select surface actors; cell size must be at least 25 cm."));
    UWorld *World = IsValid(Sources[0]) ? Sources[0]->GetWorld() : nullptr;
    if (!World || World->WorldType != EWorldType::Editor)
        return Fail(TEXT("An editor world is required."));
    FBox Bounds(ForceInit);
    TArray<UPrimitiveComponent *> Components;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(InteriorFitArea), true);
    for (AActor *Actor : Sources)
    {
        if (!IsValid(Actor) || Actor->GetWorld() != World)
            return Fail(TEXT("Invalid source actor."));
        Query.AddIgnoredActor(Actor);
        TInlineComponentArray<UPrimitiveComponent *> Owned;
        Actor->GetComponents(Owned);
        for (UPrimitiveComponent *Component : Owned)
        {
            if (!IsValid(Component) || !Component->IsRegistered() || Component->IsEditorOnly())
                continue;
            Components.Add(Component);
            Bounds += Component->Bounds.GetBox();
        }
    }
    if (!Bounds.IsValid || Components.IsEmpty() || Components.Num() > 512)
        return Fail(TEXT("No supported surface components, or too many components."));
    FAreaGrid Grid;
    Grid.Origin = Bounds.Min;
    Grid.Step = RequestedCellSize;
    do
    {
        Grid.Width = FMath::Max(1, FMath::CeilToInt(Bounds.GetSize().X / Grid.Step));
        Grid.Height = FMath::Max(1, FMath::CeilToInt(Bounds.GetSize().Y / Grid.Step));
        if (static_cast<int64>(Grid.Width) * Grid.Height <= 8192)
            break;
        Grid.Step *= 1.25;
    } while (Grid.Step < 1000000);
    if (static_cast<int64>(Grid.Width) * Grid.Height > 8192)
        return Fail(TEXT("Surface is too large."));
    Grid.Heights.Init(-TNumericLimits<double>::Max(), Grid.Width * Grid.Height);
    const FString SampleError = SampleComponents(Components, Bounds, Query, Grid);
    if (!SampleError.IsEmpty())
        return SampleError;
    return EncodeExposedCells(World, Bounds, Query, Grid, ExcludeCoveredSurface);
}
